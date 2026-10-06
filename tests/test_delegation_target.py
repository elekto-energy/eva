"""S1-lite target identity & coverage boundary (owner GO 2026-10-06).

Invariant: a consequential delegated action concerning a specific real-world object binds to the established stable
target_id; type, make, model and location never substitute for it. Coverage: an expired warranty only from explicit
dates; missing coverage evidence stays COVERAGE_NOT_ESTABLISHED (never "no insurance" / "not covered"); coverage never
grants authority. The frozen EVE core is used through a separate interpreter (see test_delegation_declarations).
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eva.authorization import AuthorizationStore
from eva.scripted_model import ScriptedModel
from eva_delegation import targets as T
from eva_delegation.agent import build_delegation_agent
from eva_delegation.declarations import build_declaration, declaration_bytes
from eva_delegation.explain import why
from eva_delegation.gate_booking import BookingGate
from eva_delegation.mandate import (MandateError, check_within_mandate, confirm_authorization, confirm_mandate,
                                    propose_authorization, propose_mandate, seal)
from eva_delegation.tools import BookingRegister, build_tools, load_offers

OFFER_ID = "DW-OFFER-001"
OFFER = load_offers()[OFFER_ID]
A1 = T.load_targets()["APPLIANCE-001"]


def target(tid: str, **meta) -> dict:
    body = {k: v for k, v in A1.items() if k != "record_sha256"}
    body.update(target_id=tid, **meta)
    return seal(body)


A2 = target("APPLIANCE-002", location="utility room")          # a second dishwasher: same type, different object


def mandate(t=A1, limit=200):
    p = propose_mandate(target=t, service="dishwasher_repair", limit_usd=limit, window="this week")
    return confirm_mandate(p, confirmed_by="Joakim Eklund", confirmation_utterance="Yes.", read_back_shown=p["read_back"])


def authorization(offer=OFFER, offer_id=OFFER_ID):
    p = propose_authorization(offer=offer, offer_id=offer_id, approved_usd=275)
    return confirm_authorization(p, confirmed_by="Joakim Eklund", confirmation_utterance="$275 is fine.",
                                 read_back_shown=p["read_back"])


def offer_for(tid: str) -> dict:
    return dict(OFFER, target_id=tid)


def write_seed(path: Path, schema: str, key: str, records: list) -> Path:
    path.write_text(json.dumps({"schema": schema, "note": "test", key: records}, indent=2), encoding="utf-8")
    return path


class FakeEve:
    def __init__(self, cpo="allow"):
        self.cpo, self.calls = cpo, []

    async def __call__(self, chain_id, ctx):
        self.calls.append((chain_id, ctx))
        return {"isError": False, "structuredContent": {
            "eve": {"chain_id": chain_id, "pre_action_status": "evaluated", "customer_policy_outcome": self.cpo,
                    "verified_chain_outcome": "ACTION_CHAIN_SUPPORTED" if self.cpo == "allow" else "HUMAN_REVIEW_REQUIRED"},
            "eve_record_id": "EVE-PAR-LOCAL-000900"}}


def run_booking(tmp_path, target_id, fake, register=None, household=None):
    register = register or BookingRegister(tmp_path / "reg.json")
    store, executions = AuthorizationStore(), []
    gate = BookingGate(fake, store, chain_bindings={OFFER_ID: "EVA-CH-DW"}, evidence_prices={OFFER_ID: 275},
                       evidence_targets={OFFER_ID: "APPLIANCE-001"})
    agent = build_delegation_agent(ScriptedModel([
        ("tool", "tu-1", "book_service_visit", {"offer_id": OFFER_ID, "price_usd": 275, "target_id": target_id}),
        ("text", "done")]), gate, build_tools(store, register, load_offers(), household or {"APPLIANCE-001": A1},
                                              executions, []))
    agent("go")
    return gate, executions, register


# ================================================================ T1 correct target
def test_t1_correct_target_passes_the_target_check_and_the_other_constraints_still_govern(tmp_path):
    c = check_within_mandate(mandate=mandate(A1, 200), offer_id=OFFER_ID, offer=OFFER)
    assert (c["target_id"], c["offer_target_id"], c["basis"], c["within_mandate"]) == \
        ("APPLIANCE-001", "APPLIANCE-001", "QUOTE_EXCEEDS_MANDATE_LIMIT", False)
    assert check_within_mandate(mandate=mandate(A1, 300), offer_id=OFFER_ID, offer=OFFER)["basis"] == "WITHIN_MANDATE_LIMIT"
    gate, executions, reg = run_booking(tmp_path, "APPLIANCE-001", FakeEve("allow"))
    assert gate.decisions[0].decision == "ALLOW" and [e["executed"] for e in executions] == [True]
    assert reg.load()["bookings"][OFFER_ID]["target_id"] == "APPLIANCE-001"


# ================================================================ T2 two dishwashers
def test_t2_resolution_never_picks_one_of_two_dishwashers():
    two = {"APPLIANCE-001": A1, "APPLIANCE-002": A2}
    r = T.resolve(two, "dishwasher")
    assert r == {"status": "NOT_ESTABLISHED", "reason": "AMBIGUOUS_TARGET", "candidates": ["APPLIANCE-001", "APPLIANCE-002"]}
    assert T.resolve({}, "dishwasher")["reason"] == "NO_TARGET_OF_TYPE"
    assert T.resolve({"APPLIANCE-001": A1}, "dishwasher")["target_id"] == "APPLIANCE-001"


def test_t2_find_household_targets_tool_reports_not_established_for_two(tmp_path):
    two = {"APPLIANCE-001": A1, "APPLIANCE-002": A2}
    tools = {t.tool_name: t for t in build_tools(AuthorizationStore(), BookingRegister(tmp_path / "r.json"),
                                                 load_offers(), two, [], [])}
    out = json.loads(tools["find_household_targets"]._tool_func(target_type="dishwasher"))
    assert out["status"] == "NOT_ESTABLISHED" and out["candidates"] == ["APPLIANCE-001", "APPLIANCE-002"]
    assert "target_id" not in out


def test_t2_gate_refuses_the_other_dishwasher_before_eve_and_books_nothing(tmp_path):
    fake = FakeEve("allow")
    gate, executions, reg = run_booking(tmp_path, "APPLIANCE-002", fake,
                                        household={"APPLIANCE-001": A1, "APPLIANCE-002": A2})
    assert gate.decisions[0].decision == "DENY" and gate.decisions[0].reason == "TARGET_NOT_IN_EVIDENCE"
    assert fake.calls == [] and executions == [] and reg.load()["bookings"] == {}


def test_t2_check_and_authorization_never_cross_targets():
    m1 = mandate(A1, 200)
    c = check_within_mandate(mandate=m1, offer_id=OFFER_ID, offer=offer_for("APPLIANCE-002"))
    assert c["basis"] == "TARGET_MISMATCH" and c["within_mandate"] is False
    big = mandate(A1, 1000)                                       # even far under the limit: still the wrong object
    assert check_within_mandate(mandate=big, offer_id=OFFER_ID, offer=offer_for("APPLIANCE-002"))["basis"] == "TARGET_MISMATCH"
    auth_other = authorization(offer=offer_for("APPLIANCE-002"))  # approval of the exact offer, but for the other object
    c = check_within_mandate(mandate=m1, offer_id=OFFER_ID, offer=OFFER, authorization=auth_other)
    assert c["within_mandate"] is False and c["basis"] == "QUOTE_EXCEEDS_MANDATE_LIMIT"


def test_t2_proposals_refuse_an_object_of_the_wrong_type_and_records_carry_the_id():
    with pytest.raises(MandateError, match="not performed on a"):
        propose_mandate(target=target("APPLIANCE-003", target_type="washing_machine"), service="dishwasher_repair",
                        limit_usd=200, window="this week")
    assert mandate(A2)["target_id"] == "APPLIANCE-002" and "APPLIANCE-002" in mandate(A2)["read_back"]


# ================================================================ T3 metadata never substitutes for the id
def test_t3_tampered_target_metadata_fails_closed(tmp_path):
    bad = dict(A1, model="SYNTH-DW-999")                          # seal no longer verifies
    path = write_seed(tmp_path / "t.json", T.TARGETS_SCHEMA, "targets", [bad])
    with pytest.raises(T.TargetError):
        T.load_targets(path)
    a = why("Why didn't you book it?", tmp_path, (), targets_path=path)
    assert a["answer_class"] == "SOURCE_VERIFICATION_FAILED" and a["statements"] == []


def test_t3_a_resealed_record_with_other_metadata_is_not_the_confirmed_target():
    m = mandate(A1)
    moved = target("APPLIANCE-001", location="garage")            # same id, validly sealed, different record
    with pytest.raises(MandateError, match="not the one the mandate was confirmed for"):
        build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, target=moved)


def test_t3_only_the_id_is_compared_never_metadata(tmp_path):
    # A same-type, same-make object with another id is refused; metadata in a request is not accepted at all.
    fake = FakeEve("allow")
    gate, *_ = run_booking(tmp_path, "APPLIANCE-001 ", fake)       # not the exact id
    assert gate.decisions[0].reason == "TARGET_NOT_IN_EVIDENCE" and fake.calls == []
    store = AuthorizationStore()
    g = BookingGate(fake, store, chain_bindings={OFFER_ID: "C"}, evidence_prices={OFFER_ID: 275},
                    evidence_targets={OFFER_ID: "APPLIANCE-001"})
    import asyncio
    d = asyncio.run(g._decide("tu", "book_service_visit", {"offer_id": OFFER_ID, "price_usd": 275,
                                                           "target_id": "APPLIANCE-001", "model": "SYNTH-DW-100"}))
    assert d.reason == "UNEXPECTED_ARGUMENTS"


# ================================================================ T4 warranty only from explicit evidence
def test_t4_warranty_expired_only_from_dates_at_a_record_time():
    facts = T.load_coverage()
    w = T.coverage_status(facts, "APPLIANCE-001", "2026-10-06T17:03:32+00:00")["manufacturer_warranty"]
    assert w["status"] == "EXPIRED" and w["warranty_end"] == "2025-03-14" and w["record"]["record_sha256"]
    assert T.coverage_status(facts, "APPLIANCE-001", "2024-06-01T00:00:00+00:00")["manufacturer_warranty"]["status"] == "IN_FORCE"


def test_t4_no_or_incomplete_warranty_evidence_is_not_established(tmp_path):
    assert T.coverage_status({}, "APPLIANCE-001", "2026-10-06T00:00:00+00:00")["manufacturer_warranty"]["status"] \
        == "WARRANTY_NOT_ESTABLISHED"
    undated = seal({"schema": T.COVERAGE_FACT_SCHEMA, "target_id": "APPLIANCE-001", "fact": "manufacturer_warranty"})
    path = write_seed(tmp_path / "c.json", T.COVERAGE_SCHEMA, "facts", [undated])
    assert T.coverage_status(T.load_coverage(path), "APPLIANCE-001", "2026-10-06T00:00:00+00:00")[
        "manufacturer_warranty"]["status"] == "WARRANTY_NOT_ESTABLISHED"
    with pytest.raises(T.TargetError):
        T.coverage_status(T.load_coverage(), "APPLIANCE-001", "2026-10-06T00:00:00")   # no timezone: refused


# ================================================================ T5 missing coverage stays NOT_ESTABLISHED, grants nothing
FORBIDDEN = ("no insurance", "not covered", "uninsured", "not insured", "no coverage", "isn't covered", "is not covered")


def test_t5_missing_coverage_is_not_established_and_never_absence():
    cov = T.coverage_status(T.load_coverage(), "APPLIANCE-001", "2026-10-06T17:03:32+00:00")
    assert cov["other_repair_coverage"]["status"] == "COVERAGE_NOT_ESTABLISHED"
    src = Path(T.__file__).read_text(encoding="utf-8")
    assert "NO_INSURANCE =" not in src and "NOT_COVERED =" not in src     # no such state can be produced


def test_t5_coverage_never_enters_the_declaration_or_the_check():
    m, a = mandate(A1), authorization()
    d = declaration_bytes(build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, target=A1, authorization=a))
    for word in (b"warranty", b"coverage", b"insurance"):
        assert word not in d.lower()
    c = check_within_mandate(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=a)
    assert set(c) == {"schema", "offer_id", "target_id", "offer_target_id", "service", "quote_usd", "mandate_limit_usd",
                      "mandate_record_sha256", "authorization_record_sha256", "within_mandate", "basis", "method",
                      "record_sha256"}


# ================================================================ T6 / T7 against the frozen EVE core
CHECKOUT = os.environ.get("EVA_EVE_CHECKOUT")
needs_eve = pytest.mark.skipif(not CHECKOUT, reason="set EVA_EVE_CHECKOUT to an eve-core-v1 checkout")
REPO = Path(__file__).resolve().parent.parent
_COMPOSE = r"""
import json, os, sys, tempfile
os.environ["EVE_RUNTIME_STORE_ROOT"] = tempfile.mkdtemp(prefix="eva_dwt_store_")
sys.path.insert(0, sys.argv[1])
from eva_intake import intake as I
builder = I.load_builder()
eve = I.load_engine(builder, os.path.abspath(sys.argv[2]))
from core.eve_chain import schema
auth, mon = I.enum_values(schema)
out = []
for path in sys.argv[3:]:
    chain, _ = I.prepare_intake(builder, eve, open(path, "rb").read(), supersedes=None,
                                authorisation_statuses=auth, monitoring_statuses=mon)
    out.append({"gate": chain.action_gate, "gaps": chain.gaps})
print(json.dumps(out))
"""


def eve_compose(tmp_path, *decls):
    paths = []
    for i, d in enumerate(decls):
        p = tmp_path / f"d{i}.json"
        p.write_bytes(declaration_bytes(d))
        paths.append(str(p))
    r = subprocess.run([sys.executable, "-c", _COMPOSE, str(REPO), CHECKOUT, *paths], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_eve
def test_t6_t7_right_target_escalates_at_200_and_is_supported_after_the_275_approval(tmp_path):
    m = mandate(A1, 200)
    v1, v2 = eve_compose(tmp_path, build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, target=A1),
                         build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, target=A1,
                                           authorization=authorization()))
    assert v1["gate"] == "HUMAN_REVIEW_REQUIRED" and [g["code"] for g in v1["gaps"]] == ["APPROVAL_SCOPE_MISMATCH"]
    assert v2["gate"] == "ACTION_CHAIN_SUPPORTED" and v2["gaps"] == []


@needs_eve
def test_t2_frozen_eve_never_supports_a_cross_target_request(tmp_path):
    # mandate for APPLIANCE-001; the offer concerns APPLIANCE-002 -- even with an approval of that exact offer
    m = mandate(A1, 1000)
    other = offer_for("APPLIANCE-002")
    d = build_declaration(mandate=m, offer_id=OFFER_ID, offer=other, target=A1,
                          authorization=authorization(offer=other))
    assert d["raw"]["approval"]["approved_scope"] != d["raw"]["approval"]["requested_scope"]
    (res,) = eve_compose(tmp_path, d)
    assert res["gate"] == "HUMAN_REVIEW_REQUIRED" and [g["code"] for g in res["gaps"]] == ["APPROVAL_SCOPE_MISMATCH"]


def test_t7_booking_for_the_right_target_executes_exactly_once(tmp_path):
    reg = BookingRegister(tmp_path / "reg.json")
    run_booking(tmp_path, "APPLIANCE-001", FakeEve("allow"), register=reg)
    gate, executions, _ = run_booking(tmp_path, "APPLIANCE-001", FakeEve("allow"), register=reg)  # second attempt
    assert not any(e.get("executed") for e in executions)          # the register refuses a second booking
    assert len(reg.load()["bookings"]) == 1 and reg.load()["bookings"][OFFER_ID]["target_id"] == "APPLIANCE-001"


# ================================================================ why: coverage wording
def _escalated_session(root: Path) -> Path:
    """Minimal sealed records for one escalated booking: turn, SAVE intake with EVE's gap, mandate."""
    from eva_review.records import canonical_sha256
    ev, intakes = root / "ev", root / "intakes"
    ev.mkdir(); intakes.mkdir()
    sealed = lambda b: {**b, "record_sha256": canonical_sha256(b)}
    turn = sealed({"record_kind": "eva_i4_turn", "turn_utc": "20261006T120000000000Z", "tool_executions": [],
                   "gate_decisions": [{"tool_name": "book_service_visit", "eve_record_id": "EVE-PAR-LOCAL-000901",
                                       "decision": "DENY", "reason": "EVE_OUTCOME: escalate", "tool_use_id": "tu-1",
                                       "chain_id": "EVA-CH-" + "c" * 24, "customer_policy_outcome": "escalate",
                                       "pre_action_status": "evaluated", "verified_chain_outcome": "HUMAN_REVIEW_REQUIRED",
                                       "args": {"offer_id": OFFER_ID, "price_usd": 275, "target_id": "APPLIANCE-001"}}]})
    (ev / "TURN_20261006T120000000000Z_1.json").write_text(json.dumps(turn), encoding="utf-8")
    intake = sealed({"record_kind": "eva_chain_intake", "mode": "SAVE", "placement": "CREATED",
                     "action_class": "book_service_visit", "subject_ref": OFFER_ID, "recorded_utc": "x",
                     "chain": {"chain_id": "EVA-CH-" + "c" * 24, "gaps": [{"code": "APPROVAL_SCOPE_MISMATCH", "text": "t"}]}})
    (intakes / ("INTAKE_20261006T120000000000Z_SAVE_EVA-CH-" + "c" * 24 + ".json")).write_text(json.dumps(intake), encoding="utf-8")
    (ev / "MANDATE_20261006T110000000000Z.json").write_text(json.dumps(mandate(A1)), encoding="utf-8")
    return ev


def test_why_states_the_target_the_expired_warranty_and_not_established_coverage(tmp_path):
    ev = _escalated_session(tmp_path)
    a = why("Why didn't you book it?", ev, (tmp_path / "intakes",))
    assert a["answer_class"] == "ESTABLISHED"
    assert "APPLIANCE-001, your Bosch dishwasher in the kitchen" in a["spoken"]
    assert "The manufacturer warranty has expired." in a["spoken"]
    assert "I don't have established evidence of other applicable repair coverage." in a["spoken"]
    texts = [a["spoken"]] + [s["text"] for s in a["statements"]] + a["not_established"]
    assert not any(f in t.lower() for t in texts for f in FORBIDDEN)
    srcs = [s["source"]["file"] for s in a["statements"]]
    assert "eva_delegation/data/household_targets_seed.json" in srcs and "eva_delegation/data/coverage_facts_seed.json" in srcs
    assert any("COVERAGE_NOT_ESTABLISHED" in m for m in a["not_established"])


def test_why_without_warranty_evidence_says_not_established(tmp_path):
    ev = _escalated_session(tmp_path)
    empty = write_seed(tmp_path / "c.json", T.COVERAGE_SCHEMA, "facts", [])
    a = why("Why didn't you book it?", ev, (tmp_path / "intakes",), coverage_path=empty)
    assert "I don't have established evidence of the manufacturer warranty." in a["spoken"]
    assert "expired" not in a["spoken"].lower()
    assert any("WARRANTY_NOT_ESTABLISHED" in m for m in a["not_established"])
