"""Target negative control (S1-lite target identity, Phase 7). Local, deterministic, no network, no EVE call.

  python tools/target_negative_control.py --binding BINDING.json --intakes DIR --out-dir PACKAGE_DIR

Locks the operator binding exactly as eva_delegation.web does (D5, delegation tool set), builds the real BookingGate
with the evidence target of each bound offer, and asks it to book the bound offer at its evidence price for a WRONG
target (APPLIANCE-002, also a dishwasher). The EVE function records any call and raises: a correct gate never calls
it. Also records: a type used as an id, and deterministic resolution with two dishwashers (never picks one).
Writes one self-hashed record NEGATIVE_CONTROL_<utc>.json (exclusive create). A closed package is refused.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eva.authorization import AuthorizationStore  # noqa: E402
from eva.binding import lock_binding  # noqa: E402
from eva.scripted_model import ScriptedModel  # noqa: E402
from eva_delegation import dconfig  # noqa: E402
from eva_delegation.agent import build_delegation_agent  # noqa: E402
from eva_delegation.gate_booking import GATE_VERSION, BookingGate  # noqa: E402
from eva_delegation.mandate import seal  # noqa: E402
from eva_delegation.targets import TARGETS_FILE, load_targets, resolve  # noqa: E402
from eva_delegation.tools import BookingRegister, build_tools, load_offers  # noqa: E402

WRONG = "APPLIANCE-002"
SOURCES = ["eva_delegation/gate_booking.py", "eva_delegation/tools.py", "eva_delegation/targets.py",
           "eva_delegation/mandate.py", "eva_delegation/dconfig.py", "eva_delegation/data/service_offers_seed.json",
           "eva_delegation/data/household_targets_seed.json", "tools/target_negative_control.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class NoEve:
    """EVE must not be reached by a request the gate refuses on target identity."""
    def __init__(self):
        self.calls = []

    async def __call__(self, chain_id, ctx):
        self.calls.append({"chain_id": chain_id, "context": ctx})
        raise AssertionError("EVE was called for a request that must be refused before EVE")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binding", required=True)
    ap.add_argument("--intakes", action="append", default=[])
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    if out.is_dir() and any(out.glob("*_RUN_INDEX_*.json")):
        print(f"STOP: {out} is a closed evidence package (it holds a run index)")
        return 4

    locked = lock_binding(Path(a.binding), tuple(a.intakes), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    offers = load_offers()
    bindings = dict(locked.bindings[dconfig.ACTION_CLASS])
    evidence_targets = {oid: offers[oid]["target_id"] for oid in bindings}
    prices = {oid: offers[oid]["price_usd"] for oid in bindings}
    targets = load_targets()
    a1 = targets["APPLIANCE-001"]
    a2 = seal({**{k: v for k, v in a1.items() if k != "record_sha256"}, "target_id": WRONG,
               "location": "utility room", "note": "negative-control fixture only; not part of the target register"})
    household = {"APPLIANCE-001": a1, WRONG: a2}
    offer_id = sorted(bindings)[0]

    eve = NoEve()
    with tempfile.TemporaryDirectory() as tmp:
        register = BookingRegister(Path(tmp) / "booking_register.json")
        store, executions = AuthorizationStore(), []
        gate = BookingGate(eve, store, chain_bindings=bindings, evidence_prices=prices, evidence_targets=evidence_targets)
        request = {"offer_id": offer_id, "price_usd": prices[offer_id], "target_id": WRONG}
        agent = build_delegation_agent(ScriptedModel([("tool", "nc-1", "book_service_visit", request), ("text", "done")]),
                                       gate, build_tools(store, register, offers, household, executions, []))
        agent("Book the repair for the other dishwasher.")
        type_as_id = asyncio.run(gate._decide("nc-2", "book_service_visit",
                                              {"offer_id": offer_id, "price_usd": prices[offer_id], "target_id": "dishwasher"}))
        bookings = register.load()["bookings"]
    decisions = gate.decisions_as_dicts() + [{k: getattr(type_as_id, k) for k in ("tool_use_id", "tool_name", "args",
                                                                                    "decision", "reason", "eve_called")}]
    res = resolve(household, "dishwasher")
    passed = (all(d["decision"] == "DENY" and d["reason"] == "TARGET_NOT_IN_EVIDENCE" and not d["eve_called"]
                  for d in decisions)
              and eve.calls == [] and executions == [] and bookings == {}
              and res["status"] == "NOT_ESTABLISHED" and res["reason"] == "AMBIGUOUS_TARGET")
    rec = {
        "record_kind": "eva_target_negative_control", "record_schema_version": "eva-target-negative-control-1.0",
        "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "gate_version": GATE_VERSION,
        "binding": locked.record(), "evidence_targets": evidence_targets, "evidence_prices": prices,
        "established_target_register": {"file": "eva_delegation/data/household_targets_seed.json",
                                        "file_sha256": sha(TARGETS_FILE), "targets": sorted(targets)},
        "wrong_target_fixture": {"target": a2, "note": "a second dishwasher, same type/make/model; fixture only"},
        "requests": [request, {"offer_id": offer_id, "price_usd": prices[offer_id], "target_id": "dishwasher"}],
        "gate_decisions": decisions, "eve_calls": eve.calls, "tool_executions": executions,
        "bookings_after": bookings, "resolution_with_two_dishwashers": {k: v for k, v in res.items() if k != "target"},
        "source_identities": {s: sha(REPO / s) for s in SOURCES},
        "result": "PASS" if passed else "FAIL",
        "claims": "The gate refused a booking for another object of the same type before EVE: no EVE call, no PAR, "
                  "no booking. Target equality is by stable target_id only.",
    }
    rec["record_sha256"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"NEGATIVE_CONTROL_{rec['recorded_utc']}.json"
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"{rec['result']}  {path.name}  record_sha256={rec['record_sha256']}")
    for d in decisions:
        print(f"   {d['args'].get('target_id')!r:18} -> {d['decision']} {d['reason']}  eve_called={d['eve_called']}")
    print(f"   eve calls={len(eve.calls)}  executions={len(executions)}  bookings={bookings}  "
          f"resolution={res['status']}/{res['reason']} {res['candidates']}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
