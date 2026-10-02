"""Strict validation of an EVA evidence declaration (eva-evidence-declaration-1.0).

Rules:
- every key listed here is required unless marked optional; unknown keys are refused;
- types are checked exactly (bool is never accepted where a string is required, and vice versa);
- nothing is filled in: a value the frozen EVE adapters would otherwise default
  (identity.authority_in_scope, tool_permission.overscoped, approval.approved_scope,
  approval.requested_scope) must be declared explicitly;
- a declaration whose tool_permission.overscoped contradicts its declared scopes is refused.

This module never decides whether the evidence is true. It only refuses input that is incomplete,
malformed or self-contradictory.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

SCHEMA_ID = "eva-evidence-declaration-1.0"
ACTION_CLASSES = ("set_supplier_risk_status",)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# type tokens
STR, OPT_STR, BOOL, TS, OPT_TS, SHA, OPT_SHA = "str", "str|null", "bool", "ts", "ts|null", "sha256", "sha256|null"

TOP_KEYS = {
    "schema": STR, "action_class": STR, "subject_ref": STR, "declared_by": STR, "declared_at": TS,
    "decision": STR, "subject": STR, "expected_control_result": STR,
    "governance": "object", "raw": "object",
}

GOVERNANCE_KEYS = {
    "chain_authorisation_required": BOOL,
    "chain_authorisation_status": "enum:authorisation",
    "chain_authorised_by": OPT_STR,
    "chain_authorised_at": OPT_TS,
    "chain_authorisation_basis": OPT_STR,
    "chain_authorisation_scope": OPT_STR,
    "chain_authorisation_expires_at": OPT_TS,
    "chain_current_scope": OPT_STR,
    "chain_owner": OPT_STR,
    "chain_owner_confirmed": BOOL,
    "chain_monitoring_owner": OPT_STR,
    "chain_monitoring_status": "enum:monitoring",
    "chain_review_cycle": OPT_STR,
}

# Every field the frozen ai_agent_action adapters read, per evidence step. (required, optional)
RAW_KEYS = {
    "agent_action": ({"action_request_created": BOOL, "action_id": STR, "action": STR, "timestamp": TS}, {}),
    "tool_permission": ({"permission_checked": BOOL, "overscoped": BOOL, "agent": STR, "granted_scope": STR,
                         "required_scope": STR, "permission_ref": STR, "timestamp": TS}, {"gap": STR}),
    "identity": ({"owner_confirmed": BOOL, "authority_in_scope": BOOL, "subject": STR, "evidence_ref": STR,
                  "timestamp": TS}, {"gap": STR}),
    "ticketing": ({"exists": BOOL, "ticket_id": OPT_STR, "timestamp": TS}, {}),
    "policy_baseline": ({"loaded": BOOL, "baseline_id": OPT_STR, "timestamp": TS},
                        {"present": BOOL, "subject": STR, "evidence_ref": STR, "gap": STR}),
    "documents": ({"stored": BOOL, "sha256": OPT_SHA, "file": OPT_STR, "timestamp": TS}, {}),
    "approval": ({"approved": BOOL, "approval_id": OPT_STR, "approver": OPT_STR, "approved_scope": STR,
                  "requested_scope": STR, "timestamp": TS}, {}),
}


class DeclarationError(ValueError):
    def __init__(self, code: str, path: str, detail: str):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(f"{code} at {path}: {detail}")


def _check(value: Any, kind: str, path: str, enums: dict[str, frozenset]) -> None:
    def bad(detail: str) -> None:
        raise DeclarationError("INVALID_TYPE", path, detail)

    nullable = kind.endswith("|null")
    if nullable and value is None:
        return
    base = kind[:-5] if nullable else kind
    if base == BOOL:
        if type(value) is not bool:
            bad("expected true or false")
    elif base == "str":
        if type(value) is not str or not value.strip():
            bad("expected a non-empty string")
    elif base == "ts":
        if type(value) is not str or not TS_RE.match(value):
            bad("expected UTC timestamp YYYY-MM-DDTHH:MM:SSZ")
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            bad("not a real calendar time")
    elif base == "sha256":
        if type(value) is not str or not SHA256_RE.match(value):
            bad("expected 64 lowercase hex characters")
    elif base.startswith("enum:"):
        allowed = enums[base[5:]]
        if type(value) is not str or value not in allowed:
            bad(f"expected one of {sorted(allowed)}")
    elif base == "object":
        if type(value) is not dict:
            bad("expected an object")
    else:  # pragma: no cover - programming error
        raise AssertionError(kind)


def _exact_keys(obj: dict, required: dict, optional: dict, path: str) -> None:
    missing = sorted(set(required) - set(obj))
    if missing:
        raise DeclarationError("MISSING_FIELD", f"{path}.{missing[0]}", "required field is absent")
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise DeclarationError("UNKNOWN_FIELD", f"{path}.{unknown[0]}", "field is not part of the schema")


def validate(decl: Any, *, authorisation_statuses: frozenset, monitoring_statuses: frozenset) -> dict:
    """Return the declaration unchanged if it is valid; raise DeclarationError otherwise.

    The enum sets must be passed explicitly (taken from the frozen EVE schema by the caller)."""
    if type(decl) is not dict:
        raise DeclarationError("INVALID_TYPE", "$", "declaration must be a JSON object")
    enums = {"authorisation": frozenset(authorisation_statuses), "monitoring": frozenset(monitoring_statuses)}
    _exact_keys(decl, TOP_KEYS, {}, "$")
    for k, kind in TOP_KEYS.items():
        _check(decl[k], kind, f"$.{k}", enums)
    if decl["schema"] != SCHEMA_ID:
        raise DeclarationError("UNSUPPORTED_SCHEMA", "$.schema", f"expected {SCHEMA_ID}")
    if decl["action_class"] not in ACTION_CLASSES:
        raise DeclarationError("UNSUPPORTED_ACTION_CLASS", "$.action_class", f"expected one of {list(ACTION_CLASSES)}")
    if not REF_RE.match(decl["subject_ref"]):
        raise DeclarationError("INVALID_TYPE", "$.subject_ref", "expected 1-64 characters [A-Za-z0-9._-]")

    gov = decl["governance"]
    _exact_keys(gov, GOVERNANCE_KEYS, {}, "$.governance")
    for k, kind in GOVERNANCE_KEYS.items():
        _check(gov[k], kind, f"$.governance.{k}", enums)

    raw = decl["raw"]
    _exact_keys(raw, RAW_KEYS, {}, "$.raw")
    for step, (required, optional) in RAW_KEYS.items():
        _check(raw[step], "object", f"$.raw.{step}", enums)
        _exact_keys(raw[step], required, optional, f"$.raw.{step}")
        for k, kind in {**required, **optional}.items():
            if k in raw[step]:
                _check(raw[step][k], kind, f"$.raw.{step}.{k}", enums)

    tp = raw["tool_permission"]
    scopes_differ = tp["granted_scope"] != tp["required_scope"]
    if tp["overscoped"] is False and scopes_differ:
        raise DeclarationError("INCONSISTENT_OVERSCOPED", "$.raw.tool_permission.overscoped",
                               "declared false, but granted_scope differs from required_scope")
    if tp["overscoped"] is True and not scopes_differ:
        raise DeclarationError("INCONSISTENT_OVERSCOPED", "$.raw.tool_permission.overscoped",
                               "declared true, but granted_scope equals required_scope")
    return decl


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def chain_id_for(decl: dict) -> str:
    """Content-addressed chain identity: same declaration -> same id; any change -> new id."""
    return "EVA-CH-" + canonical_sha256(decl)[:24]


def load_json_strict(text: str) -> Any:
    """Parse JSON, refusing duplicate keys (a later duplicate must never silently win)."""
    def hook(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                raise DeclarationError("DUPLICATE_KEY", k, "key appears more than once")
            seen[k] = v
        return seen
    return json.loads(text, object_pairs_hook=hook)
