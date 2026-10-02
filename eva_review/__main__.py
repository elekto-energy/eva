"""python -m eva_review  queue | review | export   (decision D4, blob 2869b55c...)

  queue   --turns DIR [--turns DIR ...] --reviews DIR
  review  --turns DIR [...] --reviews DIR --par PAR_ID --outcome NEW_EVIDENCE|DECLINED|HANDLED_BY_HUMAN
          --reviewer NAME [--note TEXT] [--intake INTAKE_RECORD_FILE]
  export  --turns DIR [...] --reviews DIR [--intakes DIR ...] --par PAR_ID --out DIR

Every record is verified (self-hash) on load; a single unverifiable record stops the command.
Nothing here executes an action or contacts EVE.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import audit, review
from .records import RecordError, load_dir, load_record


def _load(dirs, pattern, kinds):
    out = []
    for d in dirs or []:
        out += load_dir(Path(d), pattern, kinds)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eva_review", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("queue", "review", "export"):
        p = sub.add_parser(name)
        p.add_argument("--turns", action="append", required=True)
        p.add_argument("--reviews", required=True)
        if name == "review":
            p.add_argument("--par", required=True)
            p.add_argument("--outcome", required=True)
            p.add_argument("--reviewer", required=True)
            p.add_argument("--note", default="")
            p.add_argument("--intake")
        if name == "export":
            p.add_argument("--intakes", action="append")
            p.add_argument("--par", required=True)
            p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        turns = _load(a.turns, "TURN_*.json", ("eva_i4_turn",))
        reviews = load_dir(Path(a.reviews), "REVIEW_*.json", ("eva_review",))
        if a.cmd == "queue":
            items = review.queue(turns, reviews)
            for i in items:
                print(f"{i['eve_record_id']}  chain={i['chain_id']}  {i['verified_chain_outcome']}/{i['customer_policy_outcome']}"
                      f"  args={json.dumps(i['args'], sort_keys=True)}  turn={i['source']['file']}")
            print(f"{len(items)} open review item(s)")
        elif a.cmd == "review":
            ik = load_record(Path(a.intake), ("eva_chain_intake", "eva_review")) if a.intake else None
            path, body = review.write_review(Path(a.reviews), turns, reviews, eve_record_id=a.par, outcome=a.outcome,
                                             reviewer=a.reviewer, note=a.note, intake=ik)
            print(f"REVIEW {body['outcome']} {body['review_id']} for {a.par}: {path} record_sha256={body['record_sha256']}")
        else:
            intakes = _load(a.intakes, "INTAKE_*.json", ("eva_chain_intake",))
            bundle = audit.export_action(a.par, turns, intakes, reviews)
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            path = out / f"AUDIT_{ts}_{a.par}.json"
            with open(path, "x", encoding="utf-8", newline="\n") as fh:
                json.dump(bundle, fh, indent=2, sort_keys=True)
                fh.write("\n")
            print(f"EXPORT {a.par}: {path} export_sha256={bundle['export_sha256']}")
    except (RecordError, review.ReviewError, audit.AuditError) as exc:
        print(f"STOP {exc.code}: {exc.detail}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
