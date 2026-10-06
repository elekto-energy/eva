"""Ask EVA why -- S1-lite scope: exactly one question type, "Why didn't you book it?".

Every statement is built from a verified record and carries its source (file + sha256):
  * the EVE determination of the latest booking attempt (turn record, self-hash verified by the loader);
  * EVE's own gap text for the evaluated chain (the stored intake record, self-hash verified);
  * the user's confirmed mandate (mandate record, seal verified).
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
from .mandate import MANDATE_SCHEMA, verify_seal

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


def why(question: str, evidence_root: Path, intake_dirs: Iterable[Path] = ()) -> dict:
    if not isinstance(question, str) or not WHY_NOT_BOOKED.search(question):
        return _answer("OUT_OF_SCOPE", "I can only explain why a booking was not made, from the records.")
    try:
        turns = load_dir(Path(evidence_root), TURN_GLOB, ("eva_i4_turn",))
        dets = determinations(turns)
        intakes = [r for d in intake_dirs for r in load_dir(Path(d), INTAKE_RECORD_GLOB, ("eva_chain_intake",))]
        mandates = load_mandates(Path(evidence_root))
    except (RecordError, ReviewError, OSError, ValueError) as exc:
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
    statements = [{"text": (f"EVE returned {d['customer_policy_outcome']} for booking {args.get('offer_id')} at "
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
    if mandates:
        mfile, msha, m = mandates[-1]
        statements.append({"text": (f"Your confirmed mandate: {m['service'].replace('_', ' ')} up to ${m['limit_usd']}, "
                                    f"{m['window']} (confirmed by {m['confirmed_by']}, declared not authenticated)."),
                           "source": {"file": mfile, "file_sha256": msha, "record_sha256": m["record_sha256"]}})
    else:
        missing.append("no confirmed mandate record")

    codes = [g.get("code") for g in gaps or []]
    if codes == ["APPROVAL_SCOPE_MISMATCH"] and mandates and d["customer_policy_outcome"] == "escalate":
        # Each clause restates one statement above: the quote (turn), the mandate (mandate record), EVE's outcome and
        # its single recorded gap (intake record). No reason beyond what EVE recorded is added.
        spoken = (f"I didn't book it. The quote was ${args.get('price_usd')} and your confirmed mandate allows up to "
                  f"${mandates[-1][2]['limit_usd']}. EVE required human review: the approval on record does not "
                  f"cover this request. Evidence record {d['eve_record_id']}.")
    else:
        recorded = f" EVE recorded: {', '.join(codes)}." if codes else ""
        spoken = (f"I didn't book it. EVE returned {d['customer_policy_outcome']}.{recorded} "
                  f"Evidence record {d['eve_record_id']}.")
    return _answer("ESTABLISHED", spoken, statements, missing)
