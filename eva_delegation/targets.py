"""Established targets and coverage facts for the delegation demo (synthetic, sealed records).

Target identity (owner invariant): a consequential delegated action concerning a specific real-world object binds to
the object's stable target_id. target_type, manufacturer, model and location describe the object; they never identify
it and are never compared for authority.

Coverage (owner boundary): coverage facts DESCRIBE; they never authorize and are never an input to the mandate check,
the declaration or the gate.
  * manufacturer warranty: EXPIRED / IN_FORCE only from explicit dates in a sealed record, evaluated at a RECORD time
    (never the clock); otherwise WARRANTY_NOT_ESTABLISHED;
  * any other repair coverage (insurance, service agreement): without a record it is COVERAGE_NOT_ESTABLISHED.
    There is deliberately no NO_INSURANCE and no NOT_COVERED state: missing evidence is never turned into absence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from . import dconfig
from .mandate import TARGET_SCHEMA, MandateError, verify_seal

TARGETS_FILE = dconfig.DATA_DIR / "household_targets_seed.json"
COVERAGE_FILE = dconfig.DATA_DIR / "coverage_facts_seed.json"
TARGETS_SCHEMA = "eva-household-targets-1.0"
COVERAGE_SCHEMA = "eva-coverage-facts-1.0"
COVERAGE_FACT_SCHEMA = "eva-coverage-fact-1.0"

ESTABLISHED, NOT_ESTABLISHED = "ESTABLISHED", "NOT_ESTABLISHED"
WARRANTY_EXPIRED, WARRANTY_IN_FORCE, WARRANTY_NOT_ESTABLISHED = "EXPIRED", "IN_FORCE", "WARRANTY_NOT_ESTABLISHED"
COVERAGE_NOT_ESTABLISHED = "COVERAGE_NOT_ESTABLISHED"


class TargetError(MandateError):
    pass


def file_ref(path: Path) -> dict:
    return {"file": f"eva_delegation/data/{Path(path).name}", "file_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def load_targets(path: Path = TARGETS_FILE) -> dict[str, dict]:
    """target_id -> sealed target record. A record that does not verify, or a duplicate id, refuses the whole file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != TARGETS_SCHEMA or not isinstance(data.get("targets"), list):
        raise TargetError("unexpected household targets schema")
    out: dict[str, dict] = {}
    for rec in data["targets"]:
        if not verify_seal(rec) or rec.get("schema") != TARGET_SCHEMA or not isinstance(rec.get("target_id"), str):
            raise TargetError(f"target record does not verify: {rec.get('target_id')!r}")
        if rec["target_id"] in out:
            raise TargetError(f"duplicate target_id {rec['target_id']}")
        out[rec["target_id"]] = rec
    return out


def resolve(targets: dict[str, dict], target_type: str) -> dict:
    """Deterministic resolution of "my <target_type>": exactly one -> ESTABLISHED; none or several -> NOT_ESTABLISHED.
    It never picks one of several candidates."""
    found = sorted(tid for tid, t in targets.items() if t["target_type"] == target_type)
    if len(found) == 1:
        return {"status": ESTABLISHED, "target_id": found[0], "target": targets[found[0]]}
    return {"status": NOT_ESTABLISHED, "reason": "AMBIGUOUS_TARGET" if found else "NO_TARGET_OF_TYPE",
            "candidates": found}


def load_coverage(path: Path = COVERAGE_FILE) -> dict[str, list[dict]]:
    """target_id -> sealed coverage fact records. A record that does not verify refuses the whole file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != COVERAGE_SCHEMA or not isinstance(data.get("facts"), list):
        raise TargetError("unexpected coverage facts schema")
    out: dict[str, list[dict]] = {}
    for rec in data["facts"]:
        if not verify_seal(rec) or rec.get("schema") != COVERAGE_FACT_SCHEMA or not isinstance(rec.get("target_id"), str):
            raise TargetError(f"coverage record does not verify: {rec.get('target_id')!r}")
        out.setdefault(rec["target_id"], []).append(rec)
    return out


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def coverage_status(facts: dict[str, list[dict]], target_id: str, as_of_iso: str) -> dict:
    """Evaluate coverage for one target at a record time (ISO-8601 with offset, e.g. the mandate's confirmed_at)."""
    as_of = dt.datetime.fromisoformat(as_of_iso)
    if as_of.tzinfo is None:
        raise TargetError("as_of has no timezone")
    as_of_date = as_of.astimezone(dt.timezone.utc).date()
    recs = facts.get(target_id, [])
    warranty = [r for r in recs if r.get("fact") == "manufacturer_warranty"]
    w = {"status": WARRANTY_NOT_ESTABLISHED, "as_of": as_of_date.isoformat(), "record": None}
    if len(warranty) == 1:
        end = _date(warranty[0].get("warranty_end"))
        if end is not None:
            w = {"status": WARRANTY_EXPIRED if end < as_of_date else WARRANTY_IN_FORCE,
                 "warranty_end": end.isoformat(), "as_of": as_of_date.isoformat(), "record": warranty[0]}
    # This demo interprets no other kind of coverage record (insurance, service agreement). Whatever exists or not,
    # the state therefore stays NOT_ESTABLISHED -- never 'not covered', never 'no insurance'.
    other = [r for r in recs if r.get("fact") != "manufacturer_warranty"]
    o = {"status": COVERAGE_NOT_ESTABLISHED, "records": other}
    return {"target_id": target_id, "manufacturer_warranty": w, "other_repair_coverage": o}
