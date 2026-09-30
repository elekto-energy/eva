"""eve_mcp.server -- MCP Streamable HTTP surface for exactly one tool.

Built on the low-level MCP Server (not FastMCP) so that the input schema is a
CLOSED object: `additionalProperties: false`. The SDK validates every call
against that schema with jsonschema BEFORE the handler runs (measured: FastMCP
silently ignores unknown arguments such as `policy_config`, which is exactly
the caller-override surface this adapter must refuse). The handler validates
the arguments a second time in eve_mcp.core; two gates, one contract.

Transport: stateless Streamable HTTP at /mcp (MCP protocol 2025-11-25 as
shipped by mcp==1.30.0). No sessions, no SSE resumability, no auth in Phase 1
-- Phase 1 binds to loopback only.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Route

from eve_mcp import core

MCP_PATH = "/mcp"
ENV_HOST = "EVE_MCP_HOST"
ENV_PORT = "EVE_MCP_PORT"

TOOL_DESCRIPTION = (
    "Ask EVE for a real pre-action determination for an existing verified evidence "
    "chain. Returns the EVE envelope verbatim: verified_chain_outcome (EVE's "
    "verification state) and customer_policy_outcome (the OPERATOR-owned policy "
    "outcome selected by policy_ref). The adapter never decides, never defaults to "
    "allow, and never executes the action. Integrators must route on "
    "customer_policy_outcome exactly and fail closed on anything but 'allow'."
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["chain_id"],
    "properties": {
        "chain_id": {
            "type": "string", "minLength": 1, "maxLength": 200,
            "description": "Identifier of an EXISTING EVE evidence chain (EVE chain_id mode; no chain construction)."},
        "action_context": {
            "type": "object",
            "description": "Optional caller correlation data. Echoed by EVE verbatim; NOT evidence, NOT verified, "
                           "outside EVE's inputs_hash and outside the sealed record projection."},
        "policy_ref": {
            "type": "string", "minLength": 1,
            "description": "Selects an OPERATOR-registered, hash-pinned customer policy. "
                           "Callers cannot supply or alter policy_config."},
    },
}

_ENVELOPE_PROPERTIES = {
    "chain_id": {"type": ["string", "null"]},
    "action_context": {"type": "object"},
    "verified_chain_outcome": {"type": ["string", "null"], "enum": sorted(core.VERIFIED_CHAIN_OUTCOMES) + [None]},
    "customer_policy_outcome": {"type": "string", "enum": sorted(core.CUSTOMER_POLICY_OUTCOMES)},
    "policy_rule_id": {"type": ["string", "null"]},
    "policy_rule_triggered": {"type": "boolean"},
    "policy_version": {"type": ["string", "null"]},
    "policy_owner": {"const": core.POLICY_OWNER},
    "enforcement_owner": {"const": core.ENFORCEMENT_OWNER},
    "inputs_hash": {"type": ["string", "null"]},
    "evaluated_at": {"type": ["string", "null"]},
    "pre_action_status": {"type": "string", "enum": sorted(core.PRE_ACTION_STATUSES)},
    "boundary_note": {"type": "string"},
    "policy_rule_reason": {},
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(core.RESULT_KEYS),
    "properties": {
        "eve": {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(core.ENVELOPE_KEYS),
            "properties": _ENVELOPE_PROPERTIES,
        },
        "eve_record_id": {"type": ["string", "null"]},
        "transport": {
            "type": "object", "additionalProperties": False,
            "required": ["http_status", "endpoint_path", "elapsed_ms"],
            "properties": {"http_status": {"enum": [200, 404, 422]},
                           "endpoint_path": {"const": core.EVE_PRE_ACTION_PATH},
                           "elapsed_ms": {"type": "integer", "minimum": 0}},
        },
        "eve_instance": {
            "type": "object", "additionalProperties": False,
            "required": ["declared_tag", "declared_tree", "identity_basis"],
            "properties": {"declared_tag": {"type": "string"},
                           "declared_tree": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                           "identity_basis": {"const": core.IDENTITY_BASIS_OPERATOR_DECLARED}},
        },
        "policy": {
            "type": "object", "additionalProperties": False,
            "required": ["policy_ref", "policy_content_sha256"],
            "properties": {"policy_ref": {"type": "string"},
                           "policy_content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
        },
        "mcp": {
            "type": "object", "additionalProperties": False,
            "required": ["adapter_version", "contract_version"],
            "properties": {"adapter_version": {"type": "string"},
                           "contract_version": {"const": core.CONTRACT_VERSION}},
        },
    },
}


def _tool_definition() -> types.Tool:
    return types.Tool(
        name=core.TOOL_NAME,
        title="EVE pre-action determination",
        description=TOOL_DESCRIPTION,
        inputSchema=INPUT_SCHEMA,
        outputSchema=OUTPUT_SCHEMA,
        annotations=types.ToolAnnotations(
            readOnlyHint=False,        # EVE persists a sealed pre-action record per evaluated call
            destructiveHint=False,     # nothing is executed, changed or deleted anywhere
            idempotentHint=False,      # each evaluated call mints a new EVE record
            openWorldHint=False,       # one pinned EVE instance, nothing else
        ),
    )


def _error_call_result(err: core.EveMcpError, config: core.Config | None) -> types.CallToolResult:
    payload = core.error_result(err, config)
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2, sort_keys=True))],
        structuredContent=payload,
    )


def build_server(config: core.Config, client: core.EveClient | None = None) -> Server:
    client = client or core.EveClient(config.eve_base_url, config.timeout_seconds)
    server: Server = Server("eve-mcp", version=core.ADAPTER_VERSION)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [_tool_definition()]

    @server.call_tool(validate_input=True)
    async def _call_tool(name: str, arguments: dict[str, Any]):
        if name != core.TOOL_NAME:
            return _error_call_result(core.EveMcpError(core.E_INPUT_INVALID, f"unknown tool {name!r}"), config)
        try:
            return core.run_pre_action(config, client, arguments)
        except core.EveMcpError as err:
            return _error_call_result(err, config)

    return server


def build_app(config: core.Config, client: core.EveClient | None = None,
              allowed_hosts: list[str] | None = None) -> Starlette:
    server = build_server(config, client)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True,
                                           security_settings=security)

    class _StreamableHttpAsgi:
        """Class-based ASGI callable: Starlette mounts it as a raw ASGI app (all
        methods), whereas a plain function would be wrapped as a GET-only
        request handler (measured: POST /mcp -> 405)."""

        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    return Starlette(routes=[Route(MCP_PATH, endpoint=_StreamableHttpAsgi())],
                     lifespan=lambda app: manager.run())


def main(argv: list[str] | None = None) -> int:
    """python -m eve_mcp.server -- fail closed on any missing configuration."""
    try:
        config = core.load_config()
        host = os.environ.get(ENV_HOST, "").strip()
        port_raw = os.environ.get(ENV_PORT, "").strip()
        if not host or not port_raw:
            raise core.EveMcpError(core.E_CONFIG_MISSING, f"{ENV_HOST} and {ENV_PORT} must be set explicitly")
        port = int(port_raw)
        if host not in ("127.0.0.1", "localhost", "::1") and config.loopback_required:
            raise core.EveMcpError(core.E_CONFIG_INVALID,
                                   f"{ENV_HOST}={host!r}: Phase 1 binds to loopback only")
    except (core.EveMcpError, ValueError) as err:
        sys.stderr.write(f"eve-mcp refused to start: {err}\n")
        return 3
    import uvicorn
    sys.stderr.write(
        f"eve-mcp {core.ADAPTER_VERSION} contract {core.CONTRACT_VERSION} -> EVE {config.eve_base_url} "
        f"(declared {config.declared_tag}/{config.declared_tree[:12]}, {core.IDENTITY_BASIS_OPERATOR_DECLARED}); "
        f"policies {sorted(config.policies)}; registry sha256 {config.registry_file_sha256[:16]}\n")
    uvicorn.run(build_app(config), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
