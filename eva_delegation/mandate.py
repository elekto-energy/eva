"""Mandate and authorization records, and the deterministic within-mandate check.

Separation (owner-locked):
  * the model may PROPOSE a mandate or an authorization (it never confirms one);
  * EVA reads the proposal back verbatim; only an explicit human confirmation turns it into a record;
  * the within-mandate comparison is plain deterministic code over confirmed records -- not the model,
    and not EVE (EVE core compares no amounts; it verifies the evidence chain built from these records).

Amounts are whole US dollars (int). Floats, bools and strings are refused, never coerced.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from . import dconfig

# 1.1: every mandate, authorization and check binds the stable target_id of the object the action concerns.
# Records of schema 1.0 (no target) are not accepted by this code; they remain reproducible at commit 1199f22.
MANDATE_SCHEMA = "eva-delegation-mandate-1.1"
AUTHORIZATION_SCHEMA = "eva-delegation-authorization-1.1"
CHECK_SCHEMA = "eva-delegation-mandate-check-1.1"
TARGET_SCHEMA = "eva-household-target-1.0"


class MandateError(Exception):
    pass


def _canonical_sha256(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def seal(body: dict) -> dict:
    if "record_sha256" in body:
        raise MandateError("record is already sealed")
    out = dict(body)
    out["record_sha256"] = _canonical_sha256(body)
    return out


def verify_seal(rec: Any) -> bool:
    if not isinstance(rec, dict) or not isinstance(rec.get("record_sha256"), str):
        return False
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return _canonical_sha256(body) == rec["record_sha256"]


def _whole_usd(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MandateError(f"{field} must be a whole number of US dollars (int), got {type(value).__name__}")
    if value <= 0:
        raise MandateError(f"{field} must be positive")
    return value


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --------------------------------------------------------------------------------------------- mandate
def describe_target(target: dict) -> str:
    """Human-readable description for read-backs. Descriptive only: it never identifies the target."""
    return f"{target['manufacturer']} {target['target_type']} {target['model']}, {target['location']}"


def require_target(target: Any) -> dict:
    if not verify_seal(target) or target.get("schema") != TARGET_SCHEMA or not isinstance(target.get("target_id"), str):
        raise MandateError("target is not a sealed, established target record")
    return target


def propose_mandate(*, target: Any, service: str, limit_usd: Any, window: str) -> dict:
    """A proposal (from the model or anyone). Not evidence. Returns the proposal with its read-back text.

    The read-back names the exact target, so the human confirms WHICH object, not only which kind of object."""
    if service not in dconfig.SERVICES:
        raise MandateError(f"unsupported service {service!r}; supported: {list(dconfig.SERVICES)}")
    target = require_target(target)
    if target["target_type"] != dconfig.TARGET_TYPE_FOR_SERVICE[service]:
        raise MandateError(f"{service} is not performed on a {target['target_type']}")
    limit = _whole_usd(limit_usd, "limit_usd")
    if not isinstance(window, str) or not window.strip():
        raise MandateError("window must be a non-empty string")
    readable = service.replace("_", " ")
    tid = target["target_id"]
    return {"kind": "mandate_proposal", "target_id": tid, "target_record_sha256": target["record_sha256"],
            "service": service, "limit_usd": limit, "window": window.strip(),
            "read_back": f"Mandate: {readable} for {tid} ({describe_target(target)}), up to ${limit}, "
                         f"{window.strip()}. Confirm?"}


def confirm_mandate(proposal: dict, *, confirmed_by: str, confirmation_utterance: str,
                    read_back_shown: str) -> dict:
    """Only an explicit human confirmation of the exact read-back turns a proposal into a mandate record."""
    if proposal.get("kind") != "mandate_proposal":
        raise MandateError("not a mandate proposal")
    if read_back_shown != proposal["read_back"]:
        raise MandateError("the confirmation is not for the read-back that was shown")
    _require_confirmation(confirmed_by, confirmation_utterance)
    return seal({"schema": MANDATE_SCHEMA, "target_id": proposal["target_id"],
                 "target_record_sha256": proposal["target_record_sha256"],
                 "service": proposal["service"], "limit_usd": proposal["limit_usd"],
                 "window": proposal["window"], "read_back": proposal["read_back"],
                 "confirmed_by": confirmed_by.strip(), "confirmation_utterance": confirmation_utterance.strip(),
                 "confirmed_at": _now(), "reviewer_identity": "DECLARED_NOT_AUTHENTICATED"})


# ---------------------------------------------------------------------------------------- authorization
def propose_authorization(*, offer: dict, offer_id: str, approved_usd: Any) -> dict:
    """A proposal to approve one exact offer at one exact price (e.g. "$275 is fine"). Not evidence."""
    amount = _whole_usd(approved_usd, "approved_usd")
    if offer.get("price_usd") != amount:
        raise MandateError("an authorization approves the offer's exact price; amount differs from the offer")
    tid = offer.get("target_id")
    if not isinstance(tid, str) or not tid:
        raise MandateError("the offer names no target_id; an authorization must concern an established target")
    return {"kind": "authorization_proposal", "offer_id": offer_id, "target_id": tid, "approved_usd": amount,
            "read_back": f"Approve {offer_id} for {tid} from {offer['provider']} at ${amount}. Confirm?"}


def confirm_authorization(proposal: dict, *, confirmed_by: str, confirmation_utterance: str,
                          read_back_shown: str) -> dict:
    if proposal.get("kind") != "authorization_proposal":
        raise MandateError("not an authorization proposal")
    if read_back_shown != proposal["read_back"]:
        raise MandateError("the confirmation is not for the read-back that was shown")
    _require_confirmation(confirmed_by, confirmation_utterance)
    return seal({"schema": AUTHORIZATION_SCHEMA, "offer_id": proposal["offer_id"], "target_id": proposal["target_id"],
                 "approved_usd": proposal["approved_usd"], "read_back": proposal["read_back"],
                 "confirmed_by": confirmed_by.strip(), "confirmation_utterance": confirmation_utterance.strip(),
                 "confirmed_at": _now(), "reviewer_identity": "DECLARED_NOT_AUTHENTICATED"})


def _require_confirmation(confirmed_by: str, utterance: str) -> None:
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise MandateError("a confirmation needs the confirming person's (declared) name")
    if not isinstance(utterance, str) or not utterance.strip():
        raise MandateError("a confirmation needs the person's explicit confirmation utterance")


# ------------------------------------------------------------------------------------ deterministic check
def check_within_mandate(*, mandate: dict, offer_id: str, offer: dict, authorization: dict | None = None) -> dict:
    """Deterministic: is booking `offer_id` at its price inside what the confirmed records authorize?

    within_mandate is True only if the offer concerns the SAME stable target_id as the mandate, the offer's
    service matches the mandate, AND either the price is within the mandate limit, or a confirmed authorization
    approves exactly this offer, for this target, at exactly this price. The target is checked first: an amount
    can never hide a target mismatch. Descriptive metadata (type, make, model, location) is never compared.
    Unconfirmed or tampered records are refused (MandateError), never treated as absent or as consent.
    """
    if not verify_seal(mandate) or mandate.get("schema") != MANDATE_SCHEMA:
        raise MandateError("mandate is not a sealed, confirmed mandate record")
    if authorization is not None and (not verify_seal(authorization)
                                      or authorization.get("schema") != AUTHORIZATION_SCHEMA):
        raise MandateError("authorization is not a sealed, confirmed authorization record")
    price = _whole_usd(offer.get("price_usd"), "offer.price_usd")
    target_match = isinstance(offer.get("target_id"), str) and offer.get("target_id") == mandate["target_id"]
    service_match = offer.get("service") == mandate["service"]
    within_limit = price <= mandate["limit_usd"]
    authorized_exactly = (authorization is not None and authorization["offer_id"] == offer_id
                          and authorization["target_id"] == mandate["target_id"]
                          and authorization["approved_usd"] == price)
    within = bool(target_match and service_match and (within_limit or authorized_exactly))
    basis = ("TARGET_MISMATCH" if not target_match else
             "SERVICE_MISMATCH" if not service_match else
             "WITHIN_MANDATE_LIMIT" if within_limit else
             "EXACT_OFFER_AUTHORIZED" if authorized_exactly else
             "QUOTE_EXCEEDS_MANDATE_LIMIT")
    return seal({"schema": CHECK_SCHEMA, "offer_id": offer_id, "target_id": mandate["target_id"],
                 "offer_target_id": offer.get("target_id"), "service": offer.get("service"),
                 "quote_usd": price, "mandate_limit_usd": mandate["limit_usd"],
                 "mandate_record_sha256": mandate["record_sha256"],
                 "authorization_record_sha256": authorization["record_sha256"] if authorization else None,
                 "within_mandate": within, "basis": basis,
                 "method": "deterministic: target_id equality, service equality and integer comparison of "
                           "confirmed records"})
