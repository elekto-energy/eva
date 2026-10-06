"""Operator step (D-alpha): build a DW evidence declaration from confirmed record files.

  python -m eva_delegation.build_declaration --mandate MANDATE.json [--authorization AUTH.json]
         --offer-id DW-OFFER-001 --out-dir DIR

Writes two files with exclusive create, never overwriting:
  DW_EVIDENCE_RECORDS_<sha12>.json   the exact records (mandate, offer, authorization, recomputed check);
                                     its sha256 is the declaration's raw.documents.sha256
  DW_DECLARATION_<label>_<sha12>.json the eva-evidence-declaration-1.0 for eva_intake
A directory that holds a run index (a closed evidence package) is refused before anything is read or written.
The declaration is validated against eva_intake's own validator before it is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from eva_intake.declaration import DeclarationError, validate

from .declarations import build_declaration, declaration_bytes, evidence_records, records_bytes
from .mandate import MandateError
from .tools import load_offers

# The enum sets the frozen EVE schema defines (eve-core-v1 core/eve_chain/schema.py), as used by tests/test_intake.py.
AUTH = frozenset({"not_evaluated", "authorised", "not_authorised", "scope_mismatch", "expired"})
MON = frozenset({"not_evaluated", "monitored", "unmonitored"})


def _write_exclusive(path: Path, data: bytes) -> None:
    with open(path, "xb") as fh:
        fh.write(data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mandate", required=True)
    ap.add_argument("--authorization", default=None)
    ap.add_argument("--offer-id", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)

    out = Path(a.out_dir)
    if out.is_dir() and any(out.glob("*_RUN_INDEX_*.json")):
        print(f"STOP: {out} is a closed evidence package (it holds a run index)")
        return 4
    try:
        offers = load_offers()
        offer = offers.get(a.offer_id)
        if offer is None:
            print(f"STOP: unknown offer {a.offer_id}")
            return 2
        mandate = json.loads(Path(a.mandate).read_text(encoding="utf-8"))
        authorization = json.loads(Path(a.authorization).read_text(encoding="utf-8")) if a.authorization else None
        recs = evidence_records(mandate, a.offer_id, offer, authorization)
        decl = build_declaration(mandate=mandate, offer_id=a.offer_id, offer=offer, authorization=authorization)
        validate(decl, authorisation_statuses=AUTH, monitoring_statuses=MON)
    except (MandateError, DeclarationError, ValueError, OSError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        return 2

    rb, db = records_bytes(recs), declaration_bytes(decl)
    rsha, dsha = hashlib.sha256(rb).hexdigest(), hashlib.sha256(db).hexdigest()
    assert rsha == decl["raw"]["documents"]["sha256"]
    label = "WITH_AUTHORIZATION" if authorization else "MANDATE_ONLY"
    out.mkdir(parents=True, exist_ok=True)
    rpath = out / f"DW_EVIDENCE_RECORDS_{rsha[:12]}.json"
    dpath = out / f"DW_DECLARATION_{label}_{dsha[:12]}.json"
    try:
        _write_exclusive(rpath, rb)
        _write_exclusive(dpath, db)
    except FileExistsError as exc:
        print(f"STOP: {exc.filename} already exists; nothing is overwritten")
        return 5
    appr = decl["raw"]["approval"]
    print(f"records     {rpath} sha256={rsha}")
    print(f"declaration {dpath} sha256={dsha}")
    print(f"mandate check: within_mandate={recs['mandate_check']['within_mandate']} "
          f"basis={recs['mandate_check']['basis']}")
    print(f"approval.requested_scope = {appr['requested_scope']}")
    print(f"approval.approved_scope  = {appr['approved_scope']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
