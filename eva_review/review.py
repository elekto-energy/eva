"""Review queue and review records (decision D4, R1-R7).

The queue is DERIVED from turn records: an item is an EVE determination (PAR) that required human review
(evaluated / escalate) and was not executed. Nothing in the queue is stored or mutable.

A review record is append-only, written once per PAR, and has exactly one of three outcomes (D4 R3):
  NEW_EVIDENCE      -- (a) references an intake record of a NEW chain for the same action class and
                       subject; only a new EVE evaluation of that chain can ever let EVA act (R2, R4, R7)
  DECLINED          -- (b) no action
  HANDLED_BY_HUMAN  -- (c) an external human action; EVA executes nothing and the original escalate
                       remains an escalate (R1)
No outcome authorises anything. There is no approve, allow or execute outcome, and this module has no
path to the gate, the authorization store or the tools.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

from .records import D4_BLOB, Loaded, RecordError, canonical_sha256

OUTCOMES = ("NEW_EVIDENCE", "DECLINED", "HANDLED_BY_HUMAN")
# The consequential action classes whose EVE determinations are reviewable. Any other tool is skipped.
CONSEQUENTIAL_TOOLS = frozenset({"set_supplier_risk_status", "book_service_visit"})


class ReviewError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def determinations(turns: list[Loaded]) -> dict[str, dict]:
    """Every EVE determination for the consequential tool, keyed by PAR id, with its source turn record.
    Raises on a PAR seen twice or on an execution without an ALLOW (both are invariant violations)."""
    out: dict[str, dict] = {}
    for t in turns:
        executed_ids = {e.get("tool_use_id") for e in t.body.get("tool_executions", []) if e.get("executed")}
        for d in t.body.get("gate_decisions", []):
            if d.get("tool_name") not in CONSEQUENTIAL_TOOLS or not d.get("eve_record_id"):
                continue
            par = d["eve_record_id"]
            if par in out:
                raise ReviewError("DUPLICATE_PAR", f"{par} appears in more than one decision")
            executed = d.get("tool_use_id") in executed_ids
            if executed and d.get("decision") != "ALLOW":
                raise ReviewError("INVARIANT_EXECUTED_WITHOUT_ALLOW", f"{par} in {t.file}")
            out[par] = {"eve_record_id": par, "chain_id": d.get("chain_id"),
                        "pre_action_status": d.get("pre_action_status"),
                        "verified_chain_outcome": d.get("verified_chain_outcome"),
                        "customer_policy_outcome": d.get("customer_policy_outcome"),
                        "gate_decision": d.get("decision"), "gate_reason": d.get("reason"),
                        "tool_name": d.get("tool_name"), "args": d.get("args"),
                        "tool_use_id": d.get("tool_use_id"), "executed": executed, "source": t.ref()}
    return out


def requires_review(det: dict) -> bool:
    return (det["pre_action_status"] == "evaluated" and det["customer_policy_outcome"] == "escalate"
            and det["gate_decision"] == "DENY" and not det["executed"])


def reviews_by_par(reviews: list[Loaded]) -> dict[str, Loaded]:
    out: dict[str, Loaded] = {}
    for r in reviews:
        par = r.body["reviewed"]["eve_record_id"]
        if par in out:
            raise ReviewError("DUPLICATE_REVIEW", f"{par} has more than one review record")
        out[par] = r
    return out


def queue(turns: list[Loaded], reviews: list[Loaded]) -> list[dict]:
    """Open review items: escalate determinations without a review record. Derived, never stored."""
    done = reviews_by_par(reviews)
    return [d for par, d in sorted(determinations(turns).items()) if requires_review(d) and par not in done]


def _check_new_evidence(det: dict, intake: Loaded) -> dict:
    b = intake.body
    if b.get("record_kind") != "eva_chain_intake":
        raise ReviewError("NEW_EVIDENCE_NOT_AN_INTAKE", f"{intake.file} is a {b.get('record_kind')!r} record")
    if b.get("mode") != "SAVE" or b.get("placement") not in ("CREATED", "EXISTS_IDENTICAL"):
        raise ReviewError("NEW_EVIDENCE_NOT_STORED", f"{intake.file}: mode={b.get('mode')} placement={b.get('placement')}")
    new_chain = b["chain"]["chain_id"]
    if new_chain == det["chain_id"]:
        raise ReviewError("NEW_EVIDENCE_SAME_CHAIN", f"{new_chain} is the reviewed chain; new evidence needs its own identity")
    from .audit import subject_of                       # one subject model (audit imports this module)
    subject = subject_of(det)
    if b.get("action_class") != det["tool_name"] or b.get("subject_ref") != subject:
        raise ReviewError("NEW_EVIDENCE_OTHER_ACTION",
                          f"intake is for {b.get('action_class')}/{b.get('subject_ref')}, review is for {det['tool_name']}/{subject}")
    return {"intake_record": intake.ref(), "declaration_sha256": b["declaration_sha256"],
            "new_chain_id": new_chain, "new_chain_content_hash": b["chain"]["content_hash"],
            "supersedes_recorded_in_intake": b.get("supersedes"),
            "next_step": "A NEW EVE pre-action evaluation of new_chain_id is required; only its allow can let EVA act (D4 R2, R4)"}


def write_review(review_dir: Path, turns: list[Loaded], reviews: list[Loaded], *, eve_record_id: str,
                 outcome: str, reviewer: str, note: str, intake: Optional[Loaded] = None,
                 now: Optional[dt.datetime] = None) -> tuple[Path, dict]:
    """Write ONE review record for ONE escalate determination. Every other request is refused."""
    if outcome not in OUTCOMES:
        raise ReviewError("INVALID_OUTCOME", f"{outcome!r} is not one of {OUTCOMES}; no outcome authorises an action")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ReviewError("REVIEWER_REQUIRED", "the reviewer must be named")
    if not isinstance(note, str):
        raise ReviewError("INVALID_NOTE", "note must be text")
    dets = determinations(turns)
    det = dets.get(eve_record_id)
    if det is None:
        raise ReviewError("UNKNOWN_PAR", f"{eve_record_id} is not in the supplied turn records")
    if not requires_review(det):
        raise ReviewError("NOT_A_REVIEW_ITEM",
                          f"{eve_record_id} is {det['customer_policy_outcome']}/{det['gate_decision']}; only an escalate that was not executed can be reviewed")
    if eve_record_id in reviews_by_par(reviews):
        raise ReviewError("REVIEW_EXISTS", f"{eve_record_id} already has a review record; reviews are written once and never changed")
    if outcome == "NEW_EVIDENCE":
        if intake is None:
            raise ReviewError("NEW_EVIDENCE_REQUIRES_INTAKE", "NEW_EVIDENCE must reference the intake record of the new chain")
        new_evidence = _check_new_evidence(det, intake)
    else:
        if intake is not None:
            raise ReviewError("INTAKE_NOT_ALLOWED", f"{outcome} does not carry new evidence")
        new_evidence = None

    now = now or dt.datetime.now(dt.timezone.utc)
    body = {
        "record_kind": "eva_review", "record_schema_version": "eva-review-1.0",
        "decision_d4_blob": D4_BLOB,
        "recorded_utc": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "reviewer": reviewer, "note": note,
        "reviewed": {k: det[k] for k in ("eve_record_id", "chain_id", "pre_action_status", "verified_chain_outcome",
                                         "customer_policy_outcome", "gate_decision", "tool_name", "args",
                                         "tool_use_id", "source")},
        "outcome": outcome,
        "new_evidence": new_evidence,
        "effects": {"eva_execution": "NONE",
                    "authorizes_action": False,
                    "original_determination": "unchanged -- an escalate remains an escalate (D4 R1)",
                    "is_evidence_of_permission": False},
    }
    if outcome == "HANDLED_BY_HUMAN":
        body["effects"]["handled_by_human"] = "an external human action is recorded; EVA executed nothing (D4 R3c)"
    body["review_id"] = "EVA-RV-" + canonical_sha256(body)[:24]
    body["record_sha256"] = canonical_sha256(body)
    review_dir = Path(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"REVIEW_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{eve_record_id}.json"
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path, body
