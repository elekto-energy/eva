"""MCP wire tests against a FAKE EVE.

THE FAKE EVE IS A UNIT-TEST FIXTURE ONLY. It reproduces the MEASURED EVE
transport/envelope contract (policy_routes.py at tree a698922c...) so the
adapter's behaviour can be proven deterministically without a live instance.
Nothing here is acceptance evidence; acceptance runs only against the pinned
real EVE (acceptance/run_acceptance.py).
"""
import asyncio
import hashlib
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import uvicorn

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from eve_mcp import core, server as srv  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "policies", "policy_registry_v1.json")
TREE = "a698922c9fd740c4b114e572a626380abf1590a4"
BOUNDARY = ("EVE verifies the chain and evaluates it against customer-defined policy. The customer owns "
            "the policy and any enforcement decision. EVE does not execute, approve, block, pause or "
            "escalate the action as its own decision.")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- FAKE EVE
class FakeEve:
    """Behaviour is selected per test through `mode`; every request is recorded."""
    mode = "A"
    requests: list = []

    @classmethod
    def envelope_evaluated(cls, body, vco, cpo, rule_id, triggered, reason=None):
        pol = body.get("policy_config") or {}
        env = {
            "chain_id": body["chain_id"], "action_context": body.get("action_context") or {},
            "verified_chain_outcome": vco, "customer_policy_outcome": cpo,
            "policy_rule_id": rule_id, "policy_rule_triggered": triggered,
            "policy_version": pol.get("policy_version"), "policy_owner": "customer",
            "enforcement_owner": "customer_or_integrated_workflow",
            "inputs_hash": hashlib.sha256(json.dumps({"chain_id": body["chain_id"], "policy_config": pol},
                                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "evaluated_at": "2026-09-30T12:00:00Z", "pre_action_status": "evaluated",
            "boundary_note": BOUNDARY,
        }
        if reason is not None:
            env["policy_rule_reason"] = reason
        return env

    @classmethod
    def envelope_unevaluated(cls, status, chain_id, ctx):
        return {"chain_id": chain_id, "action_context": ctx if isinstance(ctx, dict) else {},
                "verified_chain_outcome": None, "customer_policy_outcome": "policy_not_configured",
                "policy_rule_id": None, "policy_rule_triggered": False, "policy_version": None,
                "policy_owner": "customer", "enforcement_owner": "customer_or_integrated_workflow",
                "inputs_hash": None, "evaluated_at": None, "pre_action_status": status,
                "boundary_note": "fail-closed: " + status}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, status, obj, headers=None, raw=None):
        payload = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeEve.requests.append({"method": "POST", "path": self.path, "body": body})
        m = FakeEve.mode
        if self.path != "/api/chain/pre-action":
            return self._send(404, {"detail": "no such route"})
        cid = body.get("chain_id")
        if m == "slow":
            time.sleep(3)
            return self._send(200, {})
        if m == "500":
            return self._send(500, {"error": "pre_action_record_persistence_failed", "note": "no envelope"})
        if m == "malformed":
            return self._send(200, {}, raw=b"<html>not json</html>")
        if not isinstance(cid, str) or not cid.strip():
            return self._send(422, FakeEve.envelope_unevaluated("chain_reference_required", None, body.get("action_context")))
        if cid == "NO-SUCH-CHAIN":
            hdr = {"X-EVE-Record-Id": "EVE-PAR-LOCAL-000099"} if m == "header_on_404" else None
            return self._send(404, FakeEve.envelope_unevaluated("chain_not_found", cid, body.get("action_context")), hdr)
        hdr = {"X-EVE-Record-Id": "EVE-PAR-LOCAL-000007"}
        if m == "A":
            return self._send(200, FakeEve.envelope_evaluated(body, "ACTION_CHAIN_SUPPORTED", "allow", "EMP-ALLOW-001", True, "ok"), hdr)
        if m == "B":
            return self._send(200, FakeEve.envelope_evaluated(body, "HUMAN_REVIEW_REQUIRED", "escalate", "EMP-ESCALATE-001", True, "missing"), hdr)
        if m == "no_header":
            return self._send(200, FakeEve.envelope_evaluated(body, "ACTION_CHAIN_SUPPORTED", "allow", "EMP-ALLOW-001", True))
        if m == "unlisted_vco":
            return self._send(200, FakeEve.envelope_evaluated(body, "ALLOW", "allow", "EMP-ALLOW-001", True), hdr)
        if m == "unlisted_cpo":
            return self._send(200, FakeEve.envelope_evaluated(body, "ACTION_CHAIN_SUPPORTED", "approved", "EMP-ALLOW-001", True), hdr)
        if m == "extra_key":
            e = FakeEve.envelope_evaluated(body, "ACTION_CHAIN_SUPPORTED", "allow", "EMP-ALLOW-001", True); e["proceed"] = True
            return self._send(200, e, hdr)
        if m == "missing_key":
            e = FakeEve.envelope_evaluated(body, "ACTION_CHAIN_SUPPORTED", "allow", "EMP-ALLOW-001", True); del e["inputs_hash"]
            return self._send(200, e, hdr)
        raise AssertionError("unknown fake mode " + m)


@pytest.fixture(scope="module")
def stack():
    eve_port, mcp_port = _free_port(), _free_port()
    httpd = HTTPServer(("127.0.0.1", eve_port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cfg = core.load_config({
        core.ENV_EVE_BASE_URL: f"http://127.0.0.1:{eve_port}", core.ENV_TIMEOUT: "1.5",
        core.ENV_DECLARED_TAG: "eve-core-v1", core.ENV_DECLARED_TREE: TREE,
        core.ENV_POLICY_REGISTRY: REGISTRY, core.ENV_DEFAULT_POLICY_REF: "eve-mcp-demo-policy-v1",
    })
    app = srv.build_app(cfg)
    us = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=mcp_port, log_level="error"))
    threading.Thread(target=us.run, daemon=True).start()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", mcp_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    yield {"mcp_url": f"http://127.0.0.1:{mcp_port}/mcp", "cfg": cfg, "eve_port": eve_port}
    us.should_exit = True
    httpd.shutdown()


def call(mcp_url, name, args):
    async def _run():
        async with streamable_http_client(mcp_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await s.call_tool(name, args)
    return asyncio.run(_run())


def list_tools(mcp_url):
    async def _run():
        async with streamable_http_client(mcp_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                return init, await s.list_tools()
    return asyncio.run(_run())


def structured(res):
    if res.structuredContent is not None:
        return res.structuredContent
    return json.loads(res.content[0].text)


@pytest.fixture(autouse=True)
def _reset():
    FakeEve.mode = "A"
    FakeEve.requests.clear()


# --------------------------------------------------------------------------- tests
def test_tool_listing_is_closed(stack):
    init, tools = list_tools(stack["mcp_url"])
    assert init.serverInfo.name == "eve-mcp"
    assert [t.name for t in tools.tools] == ["eve_pre_action"]
    t = tools.tools[0]
    assert t.inputSchema["additionalProperties"] is False
    assert set(t.inputSchema["properties"]) == {"chain_id", "action_context", "policy_ref"}
    assert t.outputSchema["additionalProperties"] is False


def test_case_a_like_allow(stack):
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "EVE-MCP-DEMO-A-2026-001", "action_context": {"agent_id": "agent-1"}})
    assert res.isError is False
    out = structured(res)
    assert out["eve"]["verified_chain_outcome"] == "ACTION_CHAIN_SUPPORTED"
    assert out["eve"]["customer_policy_outcome"] == "allow"
    assert out["eve_record_id"] == "EVE-PAR-LOCAL-000007"
    assert out["transport"]["http_status"] == 200
    assert out["policy"]["policy_content_sha256"] == stack["cfg"].policies["eve-mcp-demo-policy-v1"].policy_content_sha256
    # verbatim: what the fake sent is exactly what came out
    sent = FakeEve.requests[-1]["body"]
    assert out["eve"] == FakeEve.envelope_evaluated(sent, "ACTION_CHAIN_SUPPORTED", "allow", "EMP-ALLOW-001", True, "ok")


def test_case_b_like_escalate(stack):
    FakeEve.mode = "B"
    out = structured(call(stack["mcp_url"], "eve_pre_action", {"chain_id": "EVE-MCP-DEMO-B-2026-001"}))
    assert out["eve"]["customer_policy_outcome"] == "escalate"
    assert out["eve"]["verified_chain_outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert "proceed" not in out and "decision" not in out


def test_unknown_chain_404_envelope_passes_through(stack):
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "NO-SUCH-CHAIN"})
    assert res.isError is False
    out = structured(res)
    assert out["transport"]["http_status"] == 404
    assert out["eve"]["pre_action_status"] == "chain_not_found"
    assert out["eve"]["verified_chain_outcome"] is None and out["eve_record_id"] is None


def test_policy_config_from_caller_rejected_before_eve(stack):
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "X", "policy_config": {"default_outcome": "allow"}})
    assert res.isError is True
    assert FakeEve.requests == []            # the fake EVE was never contacted


def test_unknown_policy_ref_rejected_before_eve(stack):
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "X", "policy_ref": "nope"})
    assert res.isError is True and structured(res)["error"] == "POLICY_REF_UNKNOWN"
    assert FakeEve.requests == []


@pytest.mark.parametrize("args", [{}, {"chain_id": ""}, {"chain_id": 7}, {"chain_id": "X", "action_context": "s"}])
def test_malformed_input_rejected_before_eve(stack, args):
    res = call(stack["mcp_url"], "eve_pre_action", args)
    assert res.isError is True
    assert FakeEve.requests == []


@pytest.mark.parametrize("mode,code", [
    ("500", "EVE_TRANSPORT_STATUS_UNSUPPORTED"), ("malformed", "EVE_ENVELOPE_INVALID"),
    ("slow", "EVE_TIMEOUT"), ("no_header", "EVE_RECORD_ID_ABSENT"),
    ("unlisted_vco", "EVE_OUTCOME_UNLISTED"), ("unlisted_cpo", "EVE_OUTCOME_UNLISTED"),
    ("extra_key", "EVE_ENVELOPE_INVALID"), ("missing_key", "EVE_ENVELOPE_INVALID"),
])
def test_eve_side_failures_fail_closed(stack, mode, code):
    FakeEve.mode = mode
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "EVE-MCP-DEMO-A-2026-001"})
    assert res.isError is True
    out = structured(res)
    assert out["error"] == code and "eve" not in out and "eve_record_id" not in out


def test_record_header_on_404_fails_closed(stack):
    FakeEve.mode = "header_on_404"
    res = call(stack["mcp_url"], "eve_pre_action", {"chain_id": "NO-SUCH-CHAIN"})
    assert res.isError is True and structured(res)["error"] == "EVE_ENVELOPE_INVALID"


def test_eve_unreachable_fails_closed(stack):
    """Closed loopback port -> EVE_UNREACHABLE. Timeout is 5s on purpose: Windows retries SYN
    for ~2s before reporting WSAECONNREFUSED, so a 1s budget would surface as EVE_TIMEOUT there
    (measured 2026-09-30). Both codes are fail-closed; this test pins the refusal class."""
    cfg = core.load_config({
        core.ENV_EVE_BASE_URL: f"http://127.0.0.1:{_free_port()}", core.ENV_TIMEOUT: "5",
        core.ENV_DECLARED_TAG: "eve-core-v1", core.ENV_DECLARED_TREE: TREE,
        core.ENV_POLICY_REGISTRY: REGISTRY, core.ENV_DEFAULT_POLICY_REF: "eve-mcp-demo-policy-v1"})
    client = core.EveClient(cfg.eve_base_url, cfg.timeout_seconds)
    with pytest.raises(core.EveMcpError) as ei:
        core.run_pre_action(cfg, client, {"chain_id": "X"})
    assert ei.value.code == "EVE_UNREACHABLE"


def test_adapter_performs_exactly_one_eve_request_and_nothing_else(stack):
    """G: the only side effect of a tool call is ONE POST to the pre-action route."""
    call(stack["mcp_url"], "eve_pre_action", {"chain_id": "EVE-MCP-DEMO-A-2026-001"})
    assert [(r["method"], r["path"]) for r in FakeEve.requests] == [("POST", "/api/chain/pre-action")]


def test_unknown_tool_name_is_error(stack):
    res = call(stack["mcp_url"], "eve_execute_action", {"chain_id": "X"})
    assert res.isError is True
    assert FakeEve.requests == []
