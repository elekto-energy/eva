"""eve_mcp.core -- deterministic EVE pre-action integration boundary.

This module contains NO MCP code and NO model code. It is the whole semantic
boundary of the adapter:

    validate closed MCP input
    -> select an OPERATOR-registered, hash-pinned policy (never caller-supplied)
    -> one POST to the real EVE pre-action API
    -> validate the EVE transport/envelope contract (closed key set, closed
       value sets, record-id invariant)
    -> return the EVE envelope VERBATIM plus transport/policy/adapter metadata

Fail-closed rule: anything unknown, malformed, unreachable, ambiguous or
unlisted raises EveMcpError with a closed error code. There is no code path
in this module that writes a determination field or defaults to allow.

EVE contract measured from the pinned identity (tag eve-core-v1, tree
a698922c9fd740c4b114e572a626380abf1590a4): policy_routes.py, pre_action.py,
policy.py, pre_action_record.py and ADR-018 v1.1 (transport 200/404/422/500,
13-key envelope, X-EVE-Record-Id on 200, closed outcome sets).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx

CONTRACT_VERSION = "eve-mcp-pre-action-1.0"
ADAPTER_VERSION = "0.1.0"
TOOL_NAME = "eve_pre_action"

EVE_PRE_ACTION_PATH = "/api/chain/pre-action"
EVE_RECORD_HEADER = "x-eve-record-id"
IDENTITY_BASIS_OPERATOR_DECLARED = "OPERATOR_DECLARED"

# ---------------------------------------------------------------------------
# EVE contract vocabulary (measured; closed)
# ---------------------------------------------------------------------------
ENVELOPE_KEYS = frozenset({
    "chain_id", "action_context", "verified_chain_outcome",
    "customer_policy_outcome", "policy_rule_id", "policy_rule_triggered",
    "policy_version", "policy_owner", "enforcement_owner", "inputs_hash",
    "evaluated_at", "pre_action_status", "boundary_note",
})
ENVELOPE_OPTIONAL_KEYS = frozenset({"policy_rule_reason"})
VERIFIED_CHAIN_OUTCOMES = frozenset({
    "ACTION_CHAIN_SUPPORTED", "HUMAN_REVIEW_REQUIRED",
    "SUPPORTED", "PARTIAL", "NO_ANSWER",
})
CUSTOMER_POLICY_OUTCOMES = frozenset({
    "allow", "pause", "escalate", "block",
    "policy_not_configured", "no_matching_policy_rule",
})
PRE_ACTION_STATUSES = frozenset({
    "evaluated", "chain_reference_required", "chain_not_found",
})
STATUS_BY_HTTP = {200: "evaluated", 422: "chain_reference_required", 404: "chain_not_found"}
POLICY_OWNER = "customer"
ENFORCEMENT_OWNER = "customer_or_integrated_workflow"

# ---------------------------------------------------------------------------
# MCP input contract (closed)
# ---------------------------------------------------------------------------
INPUT_KEYS = frozenset({"chain_id", "action_context", "policy_ref"})
REFUSED_INPUT_KEYS = frozenset({"policy_config"})   # named so the refusal is explicit
RESULT_KEYS = frozenset({"eve", "eve_record_id", "transport", "eve_instance", "policy", "mcp"})

# ---------------------------------------------------------------------------
# Closed error vocabulary
# ---------------------------------------------------------------------------
E_INPUT_INVALID = "EVE_MCP_INPUT_INVALID"
E_POLICY_REF_UNKNOWN = "POLICY_REF_UNKNOWN"
E_POLICY_REF_REQUIRED = "POLICY_REF_REQUIRED"
E_POLICY_PIN_MISMATCH = "POLICY_PIN_MISMATCH"
E_CONFIG_MISSING = "EVE_CONFIG_MISSING"
E_CONFIG_INVALID = "EVE_CONFIG_INVALID"
E_EVE_UNREACHABLE = "EVE_UNREACHABLE"
E_EVE_TIMEOUT = "EVE_TIMEOUT"
E_EVE_TRANSPORT_STATUS_UNSUPPORTED = "EVE_TRANSPORT_STATUS_UNSUPPORTED"
E_EVE_ENVELOPE_INVALID = "EVE_ENVELOPE_INVALID"
E_EVE_OUTCOME_UNLISTED = "EVE_OUTCOME_UNLISTED"
E_EVE_RECORD_ID_ABSENT = "EVE_RECORD_ID_ABSENT"
ERROR_CODES = frozenset({
    E_INPUT_INVALID, E_POLICY_REF_UNKNOWN, E_POLICY_REF_REQUIRED,
    E_POLICY_PIN_MISMATCH, E_CONFIG_MISSING, E_CONFIG_INVALID,
    E_EVE_UNREACHABLE, E_EVE_TIMEOUT, E_EVE_TRANSPORT_STATUS_UNSUPPORTED,
    E_EVE_ENVELOPE_INVALID, E_EVE_OUTCOME_UNLISTED, E_EVE_RECORD_ID_ABSENT,
})


class EveMcpError(Exception):
    """Every negative outcome. Carries a closed code and a detail string."""

    def __init__(self, code: str, detail: str = ""):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Canonicalization -- identical to EVE core/eve_chain/schema.py sha256_hex:
# json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
# so that policy_content_sha256 is directly comparable with the
# policy_content_hash EVE binds into the sealed pre-action record.
# ---------------------------------------------------------------------------
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Configuration + operator policy registry (fail closed, hash pinned)
# ---------------------------------------------------------------------------
ENV_EVE_BASE_URL = "EVE_MCP_EVE_BASE_URL"
ENV_TIMEOUT = "EVE_MCP_TIMEOUT_SECONDS"
ENV_DECLARED_TAG = "EVE_MCP_DECLARED_TAG"
ENV_DECLARED_TREE = "EVE_MCP_DECLARED_TREE"
ENV_POLICY_REGISTRY = "EVE_MCP_POLICY_REGISTRY"
ENV_DEFAULT_POLICY_REF = "EVE_MCP_DEFAULT_POLICY_REF"
ENV_ALLOW_NON_LOOPBACK = "EVE_MCP_ALLOW_NON_LOOPBACK"
REQUIRED_ENV = (ENV_EVE_BASE_URL, ENV_TIMEOUT, ENV_DECLARED_TAG, ENV_DECLARED_TREE, ENV_POLICY_REGISTRY)

REGISTRY_SCHEMA_VERSION = "eve-mcp-policy-registry-1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TREE_RE = re.compile(r"^[0-9a-f]{40}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class Policy:
    policy_ref: str
    policy_config: Mapping[str, Any]
    policy_content_sha256: str          # canonical hash of policy_config (EVE-comparable)


@dataclass(frozen=True)
class Config:
    eve_base_url: str
    timeout_seconds: float
    declared_tag: str
    declared_tree: str
    default_policy_ref: Optional[str]
    registry_path: str
    registry_file_sha256: str
    policies: Mapping[str, Policy]
    loopback_required: bool


def _require_env(env: Mapping[str, str], key: str) -> str:
    val = env.get(key)
    if val is None or not val.strip():
        raise EveMcpError(E_CONFIG_MISSING, f"{key} is not set (an unset value never means a default)")
    return val.strip()


def load_policy_registry(path: str) -> tuple[str, dict[str, Policy]]:
    """Load the OPERATOR policy registry. Every entry carries the canonical
    sha256 it was pinned at; a mismatch is a startup failure, never a runtime
    fallback (test E)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise EveMcpError(E_CONFIG_INVALID, f"policy registry unreadable: {exc}")
    file_sha = sha256_bytes(raw)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EveMcpError(E_CONFIG_INVALID, f"policy registry is not valid JSON: {exc}")
    if not isinstance(doc, dict) or doc.get("registry_schema_version") != REGISTRY_SCHEMA_VERSION:
        raise EveMcpError(E_CONFIG_INVALID, "policy registry schema version is not "
                          + REGISTRY_SCHEMA_VERSION)
    entries = doc.get("policies")
    if not isinstance(entries, dict) or not entries:
        raise EveMcpError(E_CONFIG_INVALID, "policy registry has no 'policies' object")
    out: dict[str, Policy] = {}
    for ref, entry in entries.items():
        if not isinstance(ref, str) or not ref.strip():
            raise EveMcpError(E_CONFIG_INVALID, "policy_ref must be a non-empty string")
        if not isinstance(entry, dict) or set(entry) != {"policy_content_sha256", "policy_config"}:
            raise EveMcpError(E_CONFIG_INVALID,
                              f"registry entry {ref!r} must have exactly policy_content_sha256 + policy_config")
        cfg = entry["policy_config"]
        pinned = entry["policy_content_sha256"]
        if not isinstance(cfg, dict):
            raise EveMcpError(E_CONFIG_INVALID, f"registry entry {ref!r}: policy_config must be an object")
        if not isinstance(pinned, str) or not _SHA256_RE.match(pinned):
            raise EveMcpError(E_CONFIG_INVALID, f"registry entry {ref!r}: policy_content_sha256 malformed")
        actual = canonical_sha256(cfg)
        if actual != pinned:
            raise EveMcpError(E_POLICY_PIN_MISMATCH,
                              f"registry entry {ref!r}: canonical sha256 {actual} != pinned {pinned}")
        out[ref] = Policy(policy_ref=ref, policy_config=cfg, policy_content_sha256=actual)
    return file_sha, out


def _is_loopback(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if env is None else env
    base_url = _require_env(env, ENV_EVE_BASE_URL).rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_EVE_BASE_URL} must be an absolute http(s) URL")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_EVE_BASE_URL} must be scheme://host[:port] with no path")
    allow_non_loopback = env.get(ENV_ALLOW_NON_LOOPBACK, "").strip() == "1"
    if not allow_non_loopback and not _is_loopback(base_url):
        raise EveMcpError(E_CONFIG_INVALID,
                          f"{ENV_EVE_BASE_URL} must be a loopback http URL in Phase 1 "
                          f"(set {ENV_ALLOW_NON_LOOPBACK}=1 to override explicitly)")
    try:
        timeout = float(_require_env(env, ENV_TIMEOUT))
    except ValueError:
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_TIMEOUT} must be a number of seconds")
    if not (0 < timeout <= 120):
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_TIMEOUT} must be in (0, 120]")
    tag = _require_env(env, ENV_DECLARED_TAG)
    tree = _require_env(env, ENV_DECLARED_TREE).lower()
    if not _TREE_RE.match(tree):
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_DECLARED_TREE} must be a 40-hex git tree id")
    registry_path = _require_env(env, ENV_POLICY_REGISTRY)
    file_sha, policies = load_policy_registry(registry_path)
    default_ref = env.get(ENV_DEFAULT_POLICY_REF, "").strip() or None
    if default_ref is not None and default_ref not in policies:
        raise EveMcpError(E_CONFIG_INVALID, f"{ENV_DEFAULT_POLICY_REF}={default_ref!r} is not in the registry")
    return Config(
        eve_base_url=base_url, timeout_seconds=timeout, declared_tag=tag, declared_tree=tree,
        default_policy_ref=default_ref, registry_path=registry_path,
        registry_file_sha256=file_sha, policies=policies, loopback_required=not allow_non_loopback,
    )


# ---------------------------------------------------------------------------
# MCP input validation (closed object)
# ---------------------------------------------------------------------------
def validate_input(arguments: Any) -> tuple[str, Optional[dict], Optional[str]]:
    if not isinstance(arguments, dict):
        raise EveMcpError(E_INPUT_INVALID, "arguments must be a JSON object")
    unknown = sorted(set(arguments) - INPUT_KEYS)
    if unknown:
        refused = [k for k in unknown if k in REFUSED_INPUT_KEYS]
        if refused:
            raise EveMcpError(E_INPUT_INVALID,
                              f"caller-supplied {refused} is refused: policy is operator-owned, "
                              f"select it by policy_ref")
        raise EveMcpError(E_INPUT_INVALID, f"unknown input field(s) {unknown}; allowed: {sorted(INPUT_KEYS)}")
    chain_id = arguments.get("chain_id")
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise EveMcpError(E_INPUT_INVALID, "chain_id must be a non-empty string")
    if chain_id != chain_id.strip() or any(c.isspace() for c in chain_id):
        raise EveMcpError(E_INPUT_INVALID, "chain_id must not contain whitespace")
    if len(chain_id) > 200:
        raise EveMcpError(E_INPUT_INVALID, "chain_id longer than 200 characters")
    action_context = arguments.get("action_context")
    if action_context is not None and not isinstance(action_context, dict):
        raise EveMcpError(E_INPUT_INVALID, "action_context must be an object when supplied")
    policy_ref = arguments.get("policy_ref")
    if policy_ref is not None and (not isinstance(policy_ref, str) or not policy_ref.strip()):
        raise EveMcpError(E_INPUT_INVALID, "policy_ref must be a non-empty string when supplied")
    return chain_id, action_context, policy_ref


def select_policy(config: Config, policy_ref: Optional[str]) -> Policy:
    ref = policy_ref if policy_ref is not None else config.default_policy_ref
    if ref is None:
        raise EveMcpError(E_POLICY_REF_REQUIRED,
                          "no policy_ref supplied and no operator default configured")
    policy = config.policies.get(ref)
    if policy is None:
        raise EveMcpError(E_POLICY_REF_UNKNOWN, f"policy_ref {ref!r} is not in the operator registry")
    return policy


# ---------------------------------------------------------------------------
# EVE client -- exactly one endpoint, exactly one method
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EveResponse:
    http_status: int
    headers: Mapping[str, str]     # lower-cased header names
    body: Any
    elapsed_ms: int


class EveClient:
    def __init__(self, base_url: str, timeout_seconds: float, transport: Any = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport   # test seam only (httpx transport), never a behaviour switch

    def post_pre_action(self, body: Mapping[str, Any]) -> EveResponse:
        url = self.base_url + EVE_PRE_ACTION_PATH
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport,
                              follow_redirects=False) as client:
                resp = client.post(url, json=dict(body), headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise EveMcpError(E_EVE_TIMEOUT, f"EVE did not answer within {self.timeout_seconds}s: {exc!r}")
        except httpx.HTTPError as exc:
            raise EveMcpError(E_EVE_UNREACHABLE, f"EVE transport failure: {exc!r}")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code not in STATUS_BY_HTTP:
            raise EveMcpError(E_EVE_TRANSPORT_STATUS_UNSUPPORTED,
                              f"EVE answered HTTP {resp.status_code}; only 200/404/422 carry a governance "
                              f"envelope (500 is EVE's disjoint fail-hard path)")
        try:
            parsed = resp.json()
        except ValueError:
            raise EveMcpError(E_EVE_ENVELOPE_INVALID, "EVE response body is not JSON")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return EveResponse(resp.status_code, headers, parsed, elapsed_ms)


# ---------------------------------------------------------------------------
# EVE envelope validation (closed keys, closed values, record-id invariant)
# ---------------------------------------------------------------------------
def validate_envelope(http_status: int, body: Any, headers: Mapping[str, str]) -> tuple[dict, Optional[str]]:
    if http_status not in STATUS_BY_HTTP:
        raise EveMcpError(E_EVE_TRANSPORT_STATUS_UNSUPPORTED, f"HTTP {http_status}")
    if not isinstance(body, dict):
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "envelope is not a JSON object")
    keys = set(body)
    if keys != ENVELOPE_KEYS and keys != (ENVELOPE_KEYS | ENVELOPE_OPTIONAL_KEYS):
        raise EveMcpError(E_EVE_ENVELOPE_INVALID,
                          f"envelope key set mismatch: missing={sorted(ENVELOPE_KEYS - keys)} "
                          f"extra={sorted(keys - ENVELOPE_KEYS - ENVELOPE_OPTIONAL_KEYS)}")
    status = body["pre_action_status"]
    if status not in PRE_ACTION_STATUSES:
        raise EveMcpError(E_EVE_OUTCOME_UNLISTED, f"pre_action_status {status!r} is not in the closed set")
    if status != STATUS_BY_HTTP[http_status]:
        raise EveMcpError(E_EVE_ENVELOPE_INVALID,
                          f"HTTP {http_status} carries pre_action_status {status!r}; contract expects "
                          f"{STATUS_BY_HTTP[http_status]!r}")
    vco = body["verified_chain_outcome"]
    cpo = body["customer_policy_outcome"]
    if status == "evaluated":
        if vco not in VERIFIED_CHAIN_OUTCOMES:
            raise EveMcpError(E_EVE_OUTCOME_UNLISTED,
                              f"verified_chain_outcome {vco!r} is not in the closed five-value set")
    else:
        if vco is not None:
            raise EveMcpError(E_EVE_ENVELOPE_INVALID,
                              f"unevaluated path carries verified_chain_outcome {vco!r}; contract requires null")
    if cpo not in CUSTOMER_POLICY_OUTCOMES:
        raise EveMcpError(E_EVE_OUTCOME_UNLISTED,
                          f"customer_policy_outcome {cpo!r} is not in the closed six-value set")
    if not isinstance(body["policy_rule_triggered"], bool):
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "policy_rule_triggered must be a boolean")
    if body["policy_owner"] != POLICY_OWNER or body["enforcement_owner"] != ENFORCEMENT_OWNER:
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "policy_owner/enforcement_owner differ from the contract constants")
    if not isinstance(body["boundary_note"], str) or not body["boundary_note"]:
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "boundary_note must be a non-empty string")
    if not isinstance(body["action_context"], dict):
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "action_context must be an object")
    if "policy_rule_reason" in body and status != "evaluated":
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "policy_rule_reason may only appear on the evaluated path")
    record_id = headers.get(EVE_RECORD_HEADER)
    if http_status == 200:
        if not isinstance(record_id, str) or not record_id.strip() or any(c.isspace() for c in record_id) \
                or len(record_id) > 200:
            raise EveMcpError(E_EVE_RECORD_ID_ABSENT,
                              "HTTP 200 without a usable X-EVE-Record-Id: the contract invariant "
                              "200 <=> sealed record <=> header is broken; refusing to release the outcome")
        if not isinstance(body["inputs_hash"], str) or not _SHA256_RE.match(body["inputs_hash"]):
            raise EveMcpError(E_EVE_ENVELOPE_INVALID, "evaluated envelope must carry a sha256 inputs_hash")
        return body, record_id
    if record_id is not None:
        raise EveMcpError(E_EVE_ENVELOPE_INVALID,
                          f"HTTP {http_status} carries a record id; only evaluated responses persist a record")
    if body["inputs_hash"] is not None:
        raise EveMcpError(E_EVE_ENVELOPE_INVALID, "unevaluated envelope must carry inputs_hash null")
    return body, None


# ---------------------------------------------------------------------------
# Orchestration: the whole tool, MCP-free
# ---------------------------------------------------------------------------
def build_eve_request(chain_id: str, action_context: Optional[dict], policy: Policy) -> dict:
    body: dict[str, Any] = {"chain_id": chain_id, "policy_config": dict(policy.policy_config)}
    if action_context is not None:
        body["action_context"] = action_context
    return body


def run_pre_action(config: Config, client: EveClient, arguments: Any) -> dict:
    chain_id, action_context, policy_ref = validate_input(arguments)
    policy = select_policy(config, policy_ref)
    response = client.post_pre_action(build_eve_request(chain_id, action_context, policy))
    envelope, record_id = validate_envelope(response.http_status, response.body, response.headers)
    result = {
        "eve": envelope,                        # VERBATIM EVE envelope; never rewritten
        "eve_record_id": record_id,             # EVE-issued reference from X-EVE-Record-Id (200 only)
        "transport": {
            "http_status": response.http_status,
            "endpoint_path": EVE_PRE_ACTION_PATH,
            "elapsed_ms": response.elapsed_ms,
        },
        "eve_instance": {
            "declared_tag": config.declared_tag,
            "declared_tree": config.declared_tree,
            "identity_basis": IDENTITY_BASIS_OPERATOR_DECLARED,
        },
        "policy": {
            "policy_ref": policy.policy_ref,
            "policy_content_sha256": policy.policy_content_sha256,
        },
        "mcp": {"adapter_version": ADAPTER_VERSION, "contract_version": CONTRACT_VERSION},
    }
    assert set(result) == RESULT_KEYS
    return result


def error_result(err: EveMcpError, config: Optional[Config]) -> dict:
    out: dict[str, Any] = {
        "error": err.code,
        "detail": err.detail,
        "mcp": {"adapter_version": ADAPTER_VERSION, "contract_version": CONTRACT_VERSION},
    }
    if config is not None:
        out["eve_instance"] = {
            "declared_tag": config.declared_tag,
            "declared_tree": config.declared_tree,
            "identity_basis": IDENTITY_BASIS_OPERATOR_DECLARED,
        }
    return out
