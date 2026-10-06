"""S1-lite increment 1: consequence invariant, booking gate, booking tool, mandate records and check.

No network, no Bedrock, no EVE: a fake EVE and the existing ScriptedModel drive a real Strands agent.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from eva import config as eva_config
from eva.authorization import AuthorizationStore
from eva.frozen import FROZEN_I3A_BOUNDARY, verify_frozen_boundary
from eva.scripted_model import ScriptedModel
from eva_delegation import dconfig
from eva_delegation.agent import build_delegation_agent
from eva_delegation.consequence_registry import TOOL_CONSEQUENCE, ConsequenceConfigError, check_gate_config
from eva_delegation.gate_booking import BookingGate
from eva_delegation.mandate import (MandateError, check_within_mandate, confirm_authorization, confirm_mandate,
                                    propose_authorization, propose_mandate, verify_seal)
from eva_delegation.targets import load_targets
from eva_delegation.tools import BookingRegister, build_tools, load_offers

CHAIN_V1 = "EVA-CH-DW-V1"
OFFER = "DW-OFFER-001"
TARGET = "APPLIANCE-001"
TARGET_REC = load_targets()[TARGET]


def eve_result(chain_id=CHAIN_V1, status="evaluated", cpo="allow", vco="ACTION_CHAIN_SUPPORTED",
               record="EVE-PAR-LOCAL-000099", is_error=False):
    return {"isError": is_error, "structuredContent": {
        "eve": {"chain_id": chain_id, "pre_action_status": status, "customer_policy_outcome": cpo,
                "verified_chain_outcome": vco}, "eve_record_id": record}}


class FakeEve:
    def __init__(self, response=None, exc=None, delay=0.0):
        self.response, self.exc, self.delay, self.calls = response, exc, delay, []

    async def __call__(self, chain_id, action_context):
        self.calls.append((chain_id, action_context))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.response


@pytest.fixture
def register(tmp_path):
    return BookingRegister(tmp_path / "booking_register.json")


def sha(reg):
    return hashlib.sha256(reg.path.read_bytes()).hexdigest()


def run(fake, register, turns, timeout=eva_config.GATE_TIMEOUT_SECONDS):
    store, executions, proposals = AuthorizationStore(), [], []
    offers = load_offers()
    gate = BookingGate(fake, store, chain_bindings={OFFER: CHAIN_V1},
                       evidence_prices={OFFER: offers[OFFER]["price_usd"]},
                       evidence_targets={OFFER: offers[OFFER]["target_id"]}, timeout_seconds=timeout)
    agent = build_delegation_agent(ScriptedModel(turns), gate,
                                   build_tools(store, register, offers, load_targets(), executions, proposals))
    agent("go")
    results = [c["toolResult"] for m in agent.messages for c in m.get("content", []) if "toolResult" in c]
    return gate, store, executions, results, proposals


def book(tid="tu-1", offer=OFFER, price=275, target=TARGET):
    return [("tool", tid, "book_service_visit", {"offer_id": offer, "price_usd": price, "target_id": target}),
            ("text", "done")]


# ============================================================ the mandatory consequence invariant
def test_invariant_both_gates_are_consistent_with_the_registry():
    check_gate_config(eva_config.ALLOWED_TOOLS, eva_config.CONSEQUENTIAL_TOOLS)     # frozen supplier gate
    check_gate_config(dconfig.ALLOWED_TOOLS, dconfig.CONSEQUENTIAL_TOOLS)            # booking gate


@pytest.mark.parametrize("allowed,consequential,needle", [
    (dconfig.ALLOWED_TOOLS, frozenset(), "would pass as NON_CONSEQUENTIAL"),            # forgot the gating
    (dconfig.ALLOWED_TOOLS | {"pay_invoice"}, dconfig.CONSEQUENTIAL_TOOLS, "no consequence declaration"),
    (dconfig.ALLOWED_TOOLS, dconfig.CONSEQUENTIAL_TOOLS | {"find_service_offers"}, "declared non-consequential"),
    (frozenset({"find_service_offers"}), frozenset({"book_service_visit"}), "not in the allowed set"),
])
def test_invariant_a_misconfiguration_is_refused(allowed, consequential, needle):
    with pytest.raises(ConsequenceConfigError, match=needle):
        check_gate_config(allowed, consequential)


def test_invariant_the_booking_gate_refuses_to_start_on_a_leaking_config():
    with pytest.raises(ConsequenceConfigError):
        BookingGate(FakeEve(), AuthorizationStore(), chain_bindings={OFFER: CHAIN_V1}, evidence_prices={OFFER: 275},
                    evidence_targets={OFFER: TARGET},
                    consequential_tools=frozenset())      # book_service_visit allowed but not gated


def test_invariant_every_built_tool_is_declared_and_there_is_no_confirm_tool(tmp_path):
    names = [t.tool_name for t in build_tools(AuthorizationStore(), BookingRegister(tmp_path / "r.json"),
                                              load_offers(), load_targets(), [], [])]
    assert set(names) == set(dconfig.ALLOWED_TOOLS)
    assert all(n in TOOL_CONSEQUENCE for n in names)
    assert not any("confirm" in n for n in names)            # the model can never confirm a proposal


def test_frozen_i3a_boundary_untouched():
    assert verify_frozen_boundary() == FROZEN_I3A_BOUNDARY


# ============================================================ booking gate, end to end through Strands
def test_allow_books_exactly_once(register):
    fake = FakeEve(eve_result())
    gate, store, executions, results, _ = run(fake, register, book())
    d = [x for x in gate.decisions if x.tool_name == "book_service_visit"][0]
    assert d.decision == "ALLOW" and d.eve_record_id == "EVE-PAR-LOCAL-000099" and len(fake.calls) == 1
    assert fake.calls[0][0] == CHAIN_V1 and fake.calls[0][1]["price_usd"] == 275
    assert fake.calls[0][1]["target_id"] == TARGET
    assert [e["executed"] for e in executions] == [True] and store.pending_count() == 0
    assert register.load()["bookings"][OFFER]["target_id"] == TARGET


@pytest.mark.parametrize("cpo,vco", [("escalate", "HUMAN_REVIEW_REQUIRED"), ("block", "HUMAN_REVIEW_REQUIRED"),
                                     ("pause", "HUMAN_REVIEW_REQUIRED")])
def test_every_non_allow_books_nothing(register, cpo, vco):
    before = sha(register)
    gate, store, executions, results, _ = run(FakeEve(eve_result(cpo=cpo, vco=vco)), register, book())
    d = gate.decisions[0]
    assert d.decision == "DENY" and d.reason == f"EVE_OUTCOME: {cpo}" and d.verified_chain_outcome == vco
    assert executions == [] and sha(register) == before and store.pending_count() == 0
    assert "EVE GATE: action not executed" in results[0]["content"][0]["text"]


@pytest.mark.parametrize("args,reason", [
    ({"offer_id": OFFER, "price_usd": 274, "target_id": TARGET}, "PRICE_NOT_IN_EVIDENCE"),
    ({"offer_id": OFFER, "price_usd": "275", "target_id": TARGET}, "PRICE_NOT_IN_EVIDENCE"),
    ({"offer_id": OFFER, "price_usd": True, "target_id": TARGET}, "PRICE_NOT_IN_EVIDENCE"),
    ({"offer_id": OFFER, "price_usd": 275.0, "target_id": TARGET}, "PRICE_NOT_IN_EVIDENCE"),
    ({"offer_id": "DW-OFFER-999", "price_usd": 275, "target_id": TARGET}, "NO_OPERATOR_CHAIN_BINDING"),
    ({"offer_id": OFFER, "price_usd": 275, "target_id": TARGET, "override": True}, "UNEXPECTED_ARGUMENTS"),
    ({"offer_id": OFFER}, "UNEXPECTED_ARGUMENTS"),
    ({"offer_id": OFFER, "price_usd": 275}, "UNEXPECTED_ARGUMENTS"),                       # no target at all
    ({"offer_id": OFFER, "price_usd": 275, "target_id": "APPLIANCE-002"}, "TARGET_NOT_IN_EVIDENCE"),
    ({"offer_id": OFFER, "price_usd": 275, "target_id": "dishwasher"}, "TARGET_NOT_IN_EVIDENCE"),  # a type is no id
    ({"offer_id": OFFER, "price_usd": 274, "target_id": "APPLIANCE-002"}, "TARGET_NOT_IN_EVIDENCE"),  # target first
])
def test_gate_refuses_before_calling_eve(register, args, reason):
    fake, before = FakeEve(eve_result()), sha(register)
    gate, *_ = run(fake, register, [("tool", "tu-1", "book_service_visit", args), ("text", "done")])
    assert gate.decisions[0].decision == "DENY" and gate.decisions[0].reason == reason
    assert fake.calls == [] and sha(register) == before


def test_unknown_tool_is_not_allowed(register):
    fake = FakeEve(eve_result())
    gate, *_ = run(fake, register, [("tool", "tu-1", "pay_invoice", {"amount": 1}), ("text", "done")])
    assert gate.decisions[0].reason == "TOOL_NOT_ALLOWED" and fake.calls == []


def test_non_consequential_tools_pass_without_eve(register):
    fake = FakeEve(eve_result())
    gate, _, _, results, proposals = run(fake, register, [
        ("tool", "tu-1", "find_service_offers", {"service": "dishwasher_repair"}),
        ("tool", "tu-2", "propose_mandate", {"target_id": TARGET, "service": "dishwasher_repair", "limit_usd": 200,
                                            "window": "this week"}),
        ("text", "done")])
    assert [d.decision for d in gate.decisions] == ["PASS", "PASS"] and fake.calls == []
    assert "DW-OFFER-001" in results[0]["content"][0]["text"]
    assert proposals[0]["read_back"] == ("Mandate: dishwasher repair for APPLIANCE-001 (Bosch dishwasher SYNTH-DW-100, "
                                         "kitchen), up to $200, this week. Confirm?")
    assert proposals[0]["target_id"] == TARGET and "not confirmed" in results[1]["content"][0]["text"]


@pytest.mark.parametrize("fake,reason_prefix", [
    (FakeEve(eve_result(), exc=ConnectionError("down")), "EVE_UNREACHABLE"),
    (FakeEve(eve_result(chain_id="EVA-CH-OTHER")), "CHAIN_MISMATCH"),
    (FakeEve(eve_result(record="")), "NO_RECORD"),
    (FakeEve(eve_result(is_error=True)), "EVE_MCP_TOOL_ERROR"),
    (FakeEve(eve_result(status="chain_not_found")), "NOT_EVALUATED"),
])
def test_eve_failures_fail_closed(register, fake, reason_prefix):
    before = sha(register)
    gate, store, executions, *_ = run(fake, register, book())
    assert gate.decisions[0].decision == "DENY" and gate.decisions[0].reason.startswith(reason_prefix)
    assert executions == [] and sha(register) == before and store.pending_count() == 0


def test_eve_timeout_fails_closed(register):
    gate, *_ = run(FakeEve(eve_result(), delay=0.5), register, book(), timeout=0.05)
    assert gate.decisions[0].reason == "EVE_TIMEOUT"


def test_booking_tool_refuses_without_gate_authorization(tmp_path):
    reg, executions = BookingRegister(tmp_path / "r.json"), []
    tools = {t.tool_name: t for t in build_tools(AuthorizationStore(), reg, load_offers(), load_targets(), executions, [])}

    class Ctx:
        tool_use = {"toolUseId": "tu-direct"}
    with pytest.raises(RuntimeError, match="REFUSED"):
        tools["book_service_visit"]._tool_func(offer_id=OFFER, price_usd=275, target_id=TARGET, tool_context=Ctx())
    assert reg.load()["bookings"] == {} and executions[0]["executed"] is False


def test_a_second_identical_proposal_cannot_book_twice(register):
    gate, store, executions, *_ = run(FakeEve(eve_result()), register, [
        ("tool", "tu-1", "book_service_visit", {"offer_id": OFFER, "price_usd": 275, "target_id": TARGET}),
        ("tool", "tu-2", "book_service_visit", {"offer_id": OFFER, "price_usd": 275, "target_id": TARGET}),
        ("text", "done")])
    assert [e["executed"] for e in executions] == [True]                 # the register refuses a second booking
    assert len(register.load()["bookings"]) == 1


# ============================================================ mandate records and the deterministic check
def _mandate(limit=200):
    p = propose_mandate(target=TARGET_REC, service="dishwasher_repair", limit_usd=limit, window="this week")
    return confirm_mandate(p, confirmed_by="Joakim Eklund", confirmation_utterance="Yes.", read_back_shown=p["read_back"])


def _auth(price=275):
    offer = load_offers()[OFFER]
    p = propose_authorization(offer=offer, offer_id=OFFER, approved_usd=price)
    return confirm_authorization(p, confirmed_by="Joakim Eklund", confirmation_utterance="$275 is fine.",
                                 read_back_shown=p["read_back"])


def test_quote_over_mandate_is_not_within_mandate():
    c = check_within_mandate(mandate=_mandate(200), offer_id=OFFER, offer=load_offers()[OFFER])
    assert c["within_mandate"] is False and c["basis"] == "QUOTE_EXCEEDS_MANDATE_LIMIT"
    assert (c["quote_usd"], c["mandate_limit_usd"]) == (275, 200) and verify_seal(c)


def test_confirmed_exact_authorization_makes_it_within_mandate():
    c = check_within_mandate(mandate=_mandate(200), offer_id=OFFER, offer=load_offers()[OFFER], authorization=_auth())
    assert c["within_mandate"] is True and c["basis"] == "EXACT_OFFER_AUTHORIZED"


def test_quote_under_a_higher_limit_is_within_mandate():
    c = check_within_mandate(mandate=_mandate(300), offer_id=OFFER, offer=load_offers()[OFFER])
    assert c["within_mandate"] is True and c["basis"] == "WITHIN_MANDATE_LIMIT"


def test_the_check_is_deterministic():
    m = _mandate(200)
    a = check_within_mandate(mandate=m, offer_id=OFFER, offer=load_offers()[OFFER])
    b = check_within_mandate(mandate=m, offer_id=OFFER, offer=load_offers()[OFFER])
    assert a == b


def test_an_authorization_for_another_offer_does_not_count():
    other = dict(_auth())
    other.pop("record_sha256")
    other["offer_id"] = "DW-OFFER-002"
    from eva_delegation.mandate import seal
    c = check_within_mandate(mandate=_mandate(200), offer_id=OFFER, offer=load_offers()[OFFER],
                             authorization=seal(other))
    assert c["within_mandate"] is False


def test_service_mismatch_is_never_within_mandate():
    offer = dict(load_offers()[OFFER], service="roof_repair")
    c = check_within_mandate(mandate=_mandate(300), offer_id=OFFER, offer=offer)
    assert c["within_mandate"] is False and c["basis"] == "SERVICE_MISMATCH"


def test_a_proposal_is_never_evidence():
    p = propose_mandate(target=TARGET_REC, service="dishwasher_repair", limit_usd=200, window="this week")
    with pytest.raises(MandateError):
        check_within_mandate(mandate=p, offer_id=OFFER, offer=load_offers()[OFFER])


def test_a_tampered_mandate_is_refused():
    m = _mandate(200)
    m["limit_usd"] = 500
    with pytest.raises(MandateError):
        check_within_mandate(mandate=m, offer_id=OFFER, offer=load_offers()[OFFER])


def test_confirmation_must_match_the_read_back_and_be_explicit():
    p = propose_mandate(target=TARGET_REC, service="dishwasher_repair", limit_usd=200, window="this week")
    with pytest.raises(MandateError, match="read-back"):
        confirm_mandate(p, confirmed_by="J", confirmation_utterance="Yes", read_back_shown="Mandate: up to $2000")
    with pytest.raises(MandateError, match="name"):
        confirm_mandate(p, confirmed_by=" ", confirmation_utterance="Yes", read_back_shown=p["read_back"])
    with pytest.raises(MandateError, match="utterance"):
        confirm_mandate(p, confirmed_by="J", confirmation_utterance="", read_back_shown=p["read_back"])


@pytest.mark.parametrize("bad", [200.0, "200", True, 0, -5, None])
def test_amounts_are_whole_positive_dollars(bad):
    with pytest.raises(MandateError):
        propose_mandate(target=TARGET_REC, service="dishwasher_repair", limit_usd=bad, window="this week")


def test_an_authorization_must_be_for_the_exact_offer_price():
    with pytest.raises(MandateError, match="exact price"):
        propose_authorization(offer=load_offers()[OFFER], offer_id=OFFER, approved_usd=250)


def test_unsupported_service_is_refused():
    with pytest.raises(MandateError, match="unsupported service"):
        propose_mandate(target=TARGET_REC, service="unlock_front_door", limit_usd=10, window="tonight")
