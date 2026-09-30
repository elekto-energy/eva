"""The spoken report: what the voice says after a turn.

Owner rule (I4): the spoken text is built ONLY from a small, explicit schema of observed fields
(ObservedOutcome). No model text and no free generation can reach it. compose_spoken() takes nothing
but an ObservedOutcome, uses fixed templates, maps closed enums through fixed tables, and admits
identifiers only when they match a strict pattern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Optional

from .. import config

SUPPLIER_ID_RE = re.compile(r"^SUP-[A-Z]{1,20}-\d{3}$")
RECORD_ID_RE = re.compile(r"^EVE-[A-Z0-9-]{1,48}$")


@dataclass(frozen=True)
class ObservedOutcome:
    """Every field is observed system state, never model output."""
    proposed: bool                              # the model proposed the consequential tool
    supplier_id: Optional[str]                  # argument the gate evaluated
    requested_risk_status: Optional[str]        # argument the gate evaluated
    eve_called: bool
    pre_action_status: Optional[str]            # EVE, verbatim
    customer_policy_outcome: Optional[str]      # EVE, verbatim
    eve_record_id: Optional[str]                # EVE, verbatim
    gate_decision: Optional[str]                # ALLOW | DENY
    gate_reason: Optional[str]
    tool_executed: bool                         # the tool actually ran (execution log)
    risk_before: Optional[str]                  # register, read before the turn
    risk_after: Optional[str]                   # register, read after the turn


OBSERVED_FIELDS = tuple(f.name for f in fields(ObservedOutcome))

POLICY_PHRASE = {
    "escalate": "EVE required human review.",
    "pause": "EVE paused the action.",
    "block": "EVE blocked the action.",
    "policy_not_configured": "No policy is configured for this action.",
    "no_matching_policy_rule": "No policy rule matched this action.",
}
STATUS_PHRASE = {
    "chain_reference_required": "EVE needs an evidence chain reference for this action.",
    "chain_not_found": "EVE found no evidence chain for this action.",
}
REASON_PREFIX_PHRASE = (
    ("EVE_UNREACHABLE", "EVE could not be reached."),
    ("EVE_TIMEOUT", "EVE did not answer in time."),
    ("NO_OPERATOR_CHAIN_BINDING", "This supplier has no operator-approved evidence chain."),
    ("UNEXPECTED_ARGUMENTS", "The request had unexpected details."),
    ("TOOL_NOT_ALLOWED", "That action is not allowed."),
    ("GATE_INTERNAL_ERROR", "The gate could not complete its check."),
)


def _supplier(o: ObservedOutcome) -> str:
    return o.supplier_id if o.supplier_id and SUPPLIER_ID_RE.match(o.supplier_id) else "the supplier"


def _risk(v: Optional[str]) -> Optional[str]:
    return v if v in config.RISK_STATUSES else None


def _record(o: ObservedOutcome) -> str:
    if o.eve_record_id and RECORD_ID_RE.match(o.eve_record_id):
        return f" Evidence record {o.eve_record_id}."
    return ""


def compose_spoken(o: ObservedOutcome) -> str:
    if not isinstance(o, ObservedOutcome):
        raise TypeError("compose_spoken accepts an ObservedOutcome only")
    if not o.proposed:
        return "No change was proposed. Nothing was changed."
    sup = _supplier(o)
    before, after = _risk(o.risk_before), _risk(o.risk_after)

    if o.tool_executed and o.gate_decision == "ALLOW":
        if before and after and before != after:
            return f"EVE allowed the action. {sup} risk status changed from {before} to {after}.{_record(o)}"
        if after:
            return f"EVE allowed the action. {sup} risk status is {after}; it already had that value.{_record(o)}"
        return f"EVE allowed the action. The change was applied.{_record(o)}"

    if o.tool_executed:          # executed without an ALLOW decision: must never happen; say so, claim nothing
        return f"The outcome is inconsistent and needs review.{_record(o)}"

    unchanged = f" No change was made. {sup} risk status is still {before}." if before else " No change was made."
    if o.gate_decision == "ALLOW":
        return f"EVE allowed the action, but it was not carried out.{unchanged}{_record(o)}"
    if o.eve_called and o.pre_action_status == "evaluated" and o.customer_policy_outcome in POLICY_PHRASE:
        return f"{POLICY_PHRASE[o.customer_policy_outcome]}{unchanged}{_record(o)}"
    if o.eve_called and o.pre_action_status in STATUS_PHRASE:
        return f"{STATUS_PHRASE[o.pre_action_status]}{unchanged}{_record(o)}"
    reason = o.gate_reason or ""
    for prefix, phrase in REASON_PREFIX_PHRASE:
        if reason.startswith(prefix):
            return f"{phrase} The action was stopped.{unchanged}"
    return f"The gate stopped the action.{unchanged}{_record(o)}"


def observe(decisions: list[dict], executions: list[dict], register_before: dict, register_after: dict) -> ObservedOutcome:
    """Build the ObservedOutcome from gate decisions, the execution log and register snapshots."""
    consequential = [d for d in decisions if d.get("tool_name") in config.CONSEQUENTIAL_TOOLS]
    executed = [e for e in executions if e.get("executed")]
    if not consequential:
        return ObservedOutcome(False, None, None, False, None, None, None, None, None, False, None, None)
    if executed:
        tid = executed[-1].get("tool_use_id")
        d = next((x for x in consequential if x.get("tool_use_id") == tid), consequential[-1])
    else:
        d = consequential[-1]
    args = d.get("args") or {}
    sid = args.get("supplier_id") if isinstance(args.get("supplier_id"), str) else None
    rb = (register_before.get(sid) or {}).get("risk_status") if sid else None
    ra = (register_after.get(sid) or {}).get("risk_status") if sid else None
    rrs = args.get("risk_status") if isinstance(args.get("risk_status"), str) else None
    return ObservedOutcome(True, sid, rrs, bool(d.get("eve_called")), d.get("pre_action_status"),
                           d.get("customer_policy_outcome"), d.get("eve_record_id"), d.get("decision"),
                           d.get("reason"), bool(executed), rb, ra)
