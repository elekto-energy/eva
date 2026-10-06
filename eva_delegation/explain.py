"""Ask EVA why -- S1-lite scope: exactly one question type, "Why didn't you book it?".

Every statement is built from a verified record and carries its source (file + sha256):
  * the EVE determination of the latest booking attempt (turn record, self-hash verified by the loader);
  * EVE's own gap text for the evaluated chain (the stored intake record, self-hash verified);
  * the user's confirmed mandate (mandate record, seal verified);
  * the established target the mandate names (sealed target record) and its coverage facts (sealed coverage
    records), evaluated at the mandate's confirmation time. Coverage is described, never used as a reason:
    an expired warranty is stated only from explicit dates, and missing coverage evidence stays NOT ESTABLISHED
    ("I don't have established evidence ..."), never "no insurance" or "not covered".
EVA adds no reason of its own: the gap is quoted as what EVE recorded, never paraphrased into a "because".
Answer classes: ESTABLISHED, NOT_ESTABLISHED, OUT_OF_SCOPE, SOURCE_VERIFICATION_FAILED (fail closed).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from eva_review.records import INTAKE_RECORD_GLOB, RecordError, load_dir
from eva_review.review import ReviewError, determinations

from . import dconfig
from .mandate import MANDATE_SCHEMA, MandateError, describe_target, verify_seal
from .targets import (COVERAGE_FILE, TARGETS_FILE, WARRANTY_EXPIRED, WARRANTY_IN_FORCE, coverage_status, file_ref,
                      load_coverage, load_targets)

WHY_NOT_BOOKED = re.compile(r"\bwhy\b.*\b(didn'?t|did not|not)\b.*\bbook", re.I)
TURN_GLOB = "TURN_*.json"
MANDATE_GLOB = "MANDATE_*.json"


def _answer(cls: str, spoken: str, statements: list | None = None, missing: list | None = None) -> dict:
    return {"answer_class": cls, "spoken": spoken, "statements": statements or [], "not_established": missing or []}


def load_mandates(evidence_root: Path) -> list[tuple[str, str, dict]]:
    """(file, file_sha256, record) for every mandate record; a record that does not verify is a failure."""
    out = []
    for p in sorted(Path(evidence_root).glob(MANDATE_GLOB)):
        raw = p.read_bytes()
        rec = json.loads(raw.decode("utf-8"))
        if not verify_seal(rec) or rec.get("schema") != MANDATE_SCHEMA:
            raise RecordError("RECORD_TAMPERED", f"{p.name}: mandate seal does not verify")
        out.append((p.name, hashlib.sha256(raw).hexdigest(), rec))
    return out


def why(question: str, evidence_root: Path, intake_dirs: Iterable[Path] = (), *,
        targets_path: Path = TARGETS_FILE, coverage_path: Path = COVERAGE_FILE) -> dict:
    if not isinstance(question, str) or not WHY_NOT_BOOKED.search(question):
        return _answer("OUT_OF_SCOPE", "I can only explain why a booking was not made, from the records.")
    try:
        turns = load_dir(Path(evidence_root), TURN_GLOB, ("eva_i4_turn",))
        dets = determinations(turns)
        intakes = [r for d in intake_dirs for r in load_dir(Path(d), INTAKE_RECORD_GLOB, ("eva_chain_intake",))]
        mandates = load_mandates(Path(evidence_root))
        targets, facts = load_targets(targets_path), load_coverage(coverage_path)
        tref, cref = file_ref(targets_path), file_ref(coverage_path)
    except (RecordError, ReviewError, MandateError, OSError, ValueError) as exc:
        return _answer("SOURCE_VERIFICATION_FAILED",
                       "I can't answer: a source record does not verify.",
                       missing=[f"{type(exc).__name__}: {exc}"])

    turn_utc = {t.file: t.body.get("turn_utc", "") for t in turns}
    bookings = sorted((d for d in dets.values() if d["tool_name"] == dconfig.ACTION_CLASS),
                      key=lambda d: turn_utc.get(d["source"]["file"], ""))
    if not bookings:
        return _answer("NOT_ESTABLISHED", "I have no record of a booking attempt.",
                       missing=["no booking determination in the records"])
    d = bookings[-1]
    src = d["source"]
    if d["executed"]:
        return _answer("NOT_ESTABLISHED",
                       f"The records show the latest booking was made, under EVE record {d['eve_record_id']}.",
                       statements=[{"text": f"Booking executed under EVE record {d['eve_record_id']}.", "source": src}])

    args = d.get("args") or {}
    statements = [{"text": (f"EVE returned {d['customer_policy_outcome']} for booking {args.get('offer_id')} for "
                            f"{args.get('target_id')} at "
                            f"${args.get('price_usd')} (record {d['eve_record_id']}, chain {d['chain_id']}); "
                            f"nothing was booked."), "source": src}]
    missing = []
    stored = [i for i in intakes if i.body.get("chain", {}).get("chain_id") == d["chain_id"]
              and i.body.get("mode") == "SAVE" and i.body.get("placement") in ("CREATED", "EXISTS_IDENTICAL")]
    gaps = stored[0].body["chain"].get("gaps") if stored else None
    if gaps:
        for g in gaps:
            statements.append({"text": f"EVE recorded for this evidence: {g.get('code')} -- {g.get('text')}",
                               "source": stored[0].ref()})
    else:
        missing.append("the records do not establish a more specific reason than EVE's outcome")
    target, cov = None, None
    if mandates:
        mfile, msha, m = mandates[-1]
        statements.append({"text": (f"Your confirmed mandate: {m['service'].replace('_', ' ')} for {m['target_id']}, "
                                    f"up to ${m['limit_usd']}, {m['window']} (confirmed by {m['confirmed_by']}, "
                                    f"declared not authenticated)."),
                           "source": {"file": mfile, "file_sha256": msha, "record_sha256": m["record_sha256"]}})
        target = targets.get(m["target_id"])
        if target is not None and target["record_sha256"] == m.get("target_record_sha256"):
            statements.append({"text": f"The established target: {m['target_id']} ({describe_target(target)}).",
                               "source": {**tref, "record_sha256": target["record_sha256"]}})
            cov = coverage_status(facts, m["target_id"], m["confirmed_at"])
            w = cov["manufacturer_warranty"]
            if w["status"] in (WARRANTY_EXPIRED, WARRANTY_IN_FORCE):
                statements.append({"text": (f"Manufacturer warranty: {w['status']} (ends {w['warranty_end']}, evaluated at "
                                            f"the mandate date {w['as_of']})."),
                                   "source": {**cref, "record_sha256": w["record"]["record_sha256"]}})
            else:
                missing.append(f"manufacturer warranty for {m['target_id']}: {w['status']}")
            missing.append(f"applicable insurance or service repair coverage for {m['target_id']}: "
                           f"{cov['other_repair_coverage']['status']} (no such evidence in {cref['file']})")
        else:
            target = None
            missing.append("the target named by the mandate is not established in the target records")
    else:
        missing.append("no confirmed mandate record")

    codes = [g.get("code") for g in gaps or []]
    if codes == ["APPROVAL_SCOPE_MISMATCH"] and mandates and d["customer_policy_outcome"] == "escalate":
        # Each clause restates one statement above: the quote (turn), the mandate (mandate record), EVE's outcome and
        # its single recorded gap (intake record). No reason beyond what EVE recorded is added.
        m = mandates[-1][2]
        what = (f"repairing {m['target_id']}, your {target['manufacturer']} {target['target_type']} in the "
                f"{target['location']}," if target is not None else f"the repair of {m['target_id']}")
        spoken = (f"I didn't book it. The quote for {what} was ${args.get('price_usd')} and your confirmed mandate "
                  f"allows up to ${m['limit_usd']}. ")
        if cov is not None:
            w = cov["manufacturer_warranty"]["status"]
            spoken += ("The manufacturer warranty has expired. " if w == WARRANTY_EXPIRED else
                       "The manufacturer warranty is in force. " if w == WARRANTY_IN_FORCE else
                       "I don't have established evidence of the manufacturer warranty. ")
            spoken += "I don't have established evidence of other applicable repair coverage. "
        spoken += (f"EVE required human review: the approval on record does not cover this request. "
                   f"Evidence record {d['eve_record_id']}.")
    else:
        recorded = f" EVE recorded: {', '.join(codes)}." if codes else ""
        spoken = (f"I didn't book it. EVE returned {d['customer_policy_outcome']}.{recorded} "
                  f"Evidence record {d['eve_record_id']}.")
    return _answer("ESTABLISHED", spoken, statements, missing)
