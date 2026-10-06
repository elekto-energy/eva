"""Build the DW evidence declaration deterministically from confirmed records (decision D-beta).

Inputs are records only: the confirmed mandate, the offer from the offer register, and optionally the confirmed
authorization of the exact offer. The within-mandate check is RECOMPUTED here from those records; no caller-supplied
verdict is trusted. Same records in -> byte-identical declaration out (timestamps come from the records, never
from the clock).

How the mandate check reaches EVE (measured in the frozen HumanApprovalAdapter, eve-core-v1):
  approved=true and approved_scope == requested_scope  -> SUPPORTED
  approved=true and approved_scope != requested_scope  -> APPROVAL_SCOPE_MISMATCH  (policy: escalate)
A confirmed mandate is a human approval on record, so approved=true. approved_scope is the exact requested action
only when the deterministic check says within_mandate; otherwise it is the mandate's own scope. EVE compares two
scope strings; it never compares amounts.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from . import dconfig
from .mandate import MandateError, check_within_mandate

DECLARATION_SCHEMA = "eva-evidence-declaration-1.0"
SYNTHETIC = "synthetic demo data, not a real company"


def _ts(iso: str) -> str:
    """Record timestamp (ISO-8601 with offset) -> the declaration format YYYY-MM-DDTHH:MM:SSZ, in UTC."""
    t = dt.datetime.fromisoformat(iso)
    if t.tzinfo is None:
        raise MandateError("record timestamp has no timezone")
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def requested_scope(offer_id: str, offer: dict) -> str:
    return f"{dconfig.ACTION_CLASS} {offer_id} {offer['service']} USD {offer['price_usd']}"


def mandate_scope(mandate: dict) -> str:
    return f"{dconfig.ACTION_CLASS} {mandate['service']} up to USD {mandate['limit_usd']} {mandate['window']}"


def evidence_records(mandate: dict, offer_id: str, offer: dict, authorization: dict | None) -> dict:
    """The exact records a declaration is built from, plus the recomputed check. Written next to the declaration."""
    check = check_within_mandate(mandate=mandate, offer_id=offer_id, offer=offer, authorization=authorization)
    return {"schema": "eva-delegation-evidence-records-1.0", "offer_id": offer_id, "offer": offer,
            "mandate": mandate, "authorization": authorization, "mandate_check": check}


def build_declaration(*, mandate: dict, offer_id: str, offer: dict, authorization: dict | None = None) -> dict:
    recs = evidence_records(mandate, offer_id, offer, authorization)       # recomputes and verifies seals
    check = recs["mandate_check"]
    times = [_ts(mandate["confirmed_at"])] + ([_ts(authorization["confirmed_at"])] if authorization else [])
    at = max(times)
    req = requested_scope(offer_id, offer)
    approver = (authorization or mandate)["confirmed_by"]
    records_sha = hashlib.sha256(_canonical(recs)).hexdigest()
    return {
        "schema": DECLARATION_SCHEMA,
        "action_class": dconfig.ACTION_CLASS,
        "subject_ref": offer_id,
        "declared_by": "EVA delegation demo operator (synthetic)",
        "declared_at": at,
        "decision": f"Allow the agent to book service visit {offer_id}",
        "subject": f"{offer_id} ({offer['provider']})",
        "expected_control_result": ("The agent may book the visit only within the user's confirmed mandate, or with "
                                    "the user's explicit confirmed approval of the exact offer and price"),
        "governance": {
            "chain_authorisation_required": True,
            "chain_authorisation_status": "authorised",
            "chain_authorised_by": f"EVA Synthetic Household Governance Owner ({SYNTHETIC})",
            "chain_authorised_at": _ts(mandate["confirmed_at"]),
            "chain_authorisation_basis": "eva_delegation_mandate_record",
            "chain_authorisation_scope": dconfig.ACTION_CLASS,
            "chain_authorisation_expires_at": "2027-12-31T23:59:59Z",
            "chain_current_scope": dconfig.ACTION_CLASS,
            "chain_owner": f"EVA Synthetic Household Chain Owner ({SYNTHETIC})",
            "chain_owner_confirmed": True,
            "chain_monitoring_owner": f"EVA Synthetic Household Monitoring Owner ({SYNTHETIC})",
            "chain_monitoring_status": "monitored",
            "chain_review_cycle": "per_booking",
        },
        "raw": {
            "agent_action": {"action_request_created": True, "action_id": f"EVA-DW-ACT-{offer_id}",
                             "action": req, "timestamp": at},
            "tool_permission": {"permission_checked": True, "overscoped": False,
                                "agent": f"EVA household agent ({SYNTHETIC})",
                                "granted_scope": "book:service_visit", "required_scope": "book:service_visit",
                                "permission_ref": "perm:eva:delegation:booking", "timestamp": at},
            "identity": {"owner_confirmed": True, "authority_in_scope": True, "subject": "household_member",
                         "evidence_ref": f"mandate:{mandate['record_sha256'][:16]}", "timestamp": at},
            "ticketing": {"exists": True, "ticket_id": f"EVA-DW-REQ-{offer_id}", "timestamp": at},
            "policy_baseline": {"loaded": True, "baseline_id": "EVA-DW-POL-01", "timestamp": at},
            "documents": {"stored": True, "sha256": records_sha,
                          "file": f"DW_EVIDENCE_RECORDS_{records_sha[:12]}.json", "timestamp": at},
            "approval": {"approved": True, "approval_id": f"EVA-DW-APR-{check['record_sha256'][:16]}",
                         "approver": approver,
                         "approved_scope": req if check["within_mandate"] else mandate_scope(mandate),
                         "requested_scope": req, "timestamp": at},
        },
    }


def declaration_bytes(decl: dict) -> bytes:
    """The exact bytes written for a declaration (stable formatting, LF, trailing newline)."""
    return (json.dumps(decl, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def records_bytes(recs: dict) -> bytes:
    """The canonical bytes of the evidence-records file; its sha256 equals raw.documents.sha256."""
    return _canonical(recs)
