"""S1-lite increment 3: delegation server (path i), human-only confirmation, booking via the booking gate,
"Why didn't you book it?", and the two narrow changes (A) eva/binding.py and (A') eva_review/review.py.

No network, no Bedrock, no EVE: a fake EVE behind the real PolicyObserver; intake records are synthetic but
self-hashed exactly like stored ones.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from eva import config
from eva.binding import BindingError, lock_binding
from eva_delegation import dconfig
from eva_delegation.web import create_delegation_app
from eva_review.records import canonical_sha256, load_record
from eva_review.review import CONSEQUENTIAL_TOOLS, determinations

OFFER = "DW-OFFER-001"
CH_V1 = "EVA-CH-" + "a1" * 12
CH_V2 = "EVA-CH-" + "b2" * 12
POLICY = {"policy_ref": config.POLICY_REF, "policy_content_sha256": config.POLICY_CONTENT_SHA256}
GAP_V1 = {"code": "APPROVAL_SCOPE_MISMATCH", "step_id": "human_approval", "source_system": "Human Approval",
          "text": 'Approval covers "book_service_visit dishwasher_repair up to USD 200 this week"; request includes '
                  '"book_service_visit DW-OFFER-001 dishwasher_repair USD 275"'}
MANDATE_TEXT = "Book a dishwasher repair this week. You may approve up to $200."


def sealed(body: dict) -> dict:
    return {**body, "record_sha256": canonical_sha256(body)}


def write_intake(d: Path, chain_id: str, gaps: list, subject: str = OFFER, ts: str = "20261006T120000000000Z") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    rec = sealed({"record_kind": "eva_chain_intake", "record_schema_version": "eva-chain-intake-1.0", "mode": "SAVE",
                  "placement": "CREATED", "action_class": "book_service_visit", "subject_ref": subject,
                  "chain": {"chain_id": chain_id, "content_hash": "c" * 64, "gaps": gaps,
                            "action_gate": "HUMAN_REVIEW_REQUIRED" if gaps else "ACTION_CHAIN_SUPPORTED",
                            "overall_verdict": "PARTIAL" if gaps else "SUPPORTED", "human_review_required": bool(gaps)},
                  "recorded_utc": ts, "declaration_sha256": "d" * 64, "declared_by": "test", "declared_at":
                  "2026-10-06T12:00:00Z", "eve_checkout": {"tree": "a698922c9fd740c4b114e572a626380abf1590a4"},
                  "equivalence_gate": {"status": "PASS"}, "supersedes": None})
    p = d / f"INTAKE_{ts}_SAVE_{chain_id}.json"
    p.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def write_binding(d: Path, chain_id: str, tool: str = "book_service_visit") -> Path:
    p = d / f"dw_{chain_id[-4:]}.chain_map.json"
    p.write_text(json.dumps({"schema": "eva-chain-map-1.0", "note": "test", "bindings": {tool: {OFFER: chain_id}}}),
                 encoding="utf-8")
    return p


def eve(cpo: str, chain_id: str, record: str, policy=POLICY):
    async def pre_action(chain, ctx):
        pre_action.calls.append((chain, ctx))
        vco = "ACTION_CHAIN_SUPPORTED" if cpo == "allow" else "HUMAN_REVIEW_REQUIRED"
        return {"isError": False, "structuredContent": {                    # the shape PolicyObserver reads
            "eve": {"chain_id": chain_id, "pre_action_status": "evaluated", "customer_policy_outcome": cpo,
                    "verified_chain_outcome": vco},
            "policy": {"policy_ref": policy["policy_ref"], "policy_content_sha256": policy["policy_content_sha256"]},
            "eve_record_id": record}}
    pre_action.calls = []
    return pre_action


@pytest.fixture
def dirs(tmp_path):
    return {"ev": tmp_path / "evidence", "intakes": tmp_path / "intakes", "runs": tmp_path / "runs", "root": tmp_path}


def client(dirs, pre_action=None, binding=None):
    app = create_delegation_app(evidence_root=dirs["ev"], pre_action=pre_action, runs_root=dirs["runs"],
                                binding=binding, expected_policy=POLICY, intake_dirs=(dirs["intakes"],))
    return TestClient(app)


def turn(c, utterance):
    r = c.post("/api/delegation/turn", json={"utterance": utterance, "proposer": "scripted"})
    assert r.status_code == 200, r.text
    return r.json()


def confirm_pending(c, name="Joakim Eklund", utterance="Yes."):
    p = c.get("/api/delegation/state").json()["pending"][-1]
    kind = "mandate" if p["kind"] == "mandate_proposal" else "authorization"
    return c.post("/api/delegation/confirm", json={"kind": kind, "read_back": p["read_back"], "confirmed_by": name,
                                                   "confirmation_utterance": utterance})


# ================================================================ (A) eva/binding.py
def test_a_dw_binding_is_invalid_with_the_default_tool_set(dirs):
    write_intake(dirs["intakes"], CH_V1, [GAP_V1])
    with pytest.raises(BindingError) as e:
        lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],))
    assert e.value.code == "BINDING_INVALID" and "not a consequential tool" in e.value.detail


def test_a_the_same_binding_locks_with_the_delegation_tool_set(dirs):
    write_intake(dirs["intakes"], CH_V1, [GAP_V1])
    lb = lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],),
                      consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    assert lb.bindings == {"book_service_visit": {OFFER: CH_V1}} and lb.intake_records[0]["chain_id"] == CH_V1


def test_a_b7_still_refuses_without_the_right_intake(dirs):
    with pytest.raises(BindingError) as e:
        lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],),
                     consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    assert e.value.code == "BINDING_WITHOUT_INTAKE"
    write_intake(dirs["intakes"], CH_V1, [GAP_V1], subject="DW-OFFER-999")
    with pytest.raises(BindingError) as e:
        lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],),
                     consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    assert e.value.code == "BINDING_SUBJECT_MISMATCH"


def test_a_a_supplier_binding_is_refused_with_the_delegation_tool_set(dirs):
    with pytest.raises(BindingError) as e:
        lock_binding(write_binding(dirs["root"], "EVA-CH-" + "c3" * 12, tool="set_supplier_risk_status"), (),
                     consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    assert e.value.code == "BINDING_INVALID"


def test_a_frozen_default_binding_is_unchanged():
    lb = lock_binding(None)
    assert lb.source == "frozen_default" and set(lb.bindings) == {"set_supplier_risk_status"}


# ================================================================ (A') eva_review/review.py
def test_a2_known_tools_are_both_reviewable_and_unknown_tools_are_skipped(tmp_path):
    def t(name, decisions):
        p = tmp_path / name
        p.write_text(json.dumps(sealed({"record_kind": "eva_i4_turn", "turn_utc": name, "gate_decisions": decisions,
                                        "tool_executions": []})), encoding="utf-8")
        return load_record(p, ("eva_i4_turn",))
    mk = lambda tool, par: {"tool_name": tool, "eve_record_id": par, "decision": "DENY", "tool_use_id": par,
                            "chain_id": "X", "args": {}, "customer_policy_outcome": "escalate"}
    dets = determinations([t("TURN_1.json", [mk("set_supplier_risk_status", "EVE-PAR-LOCAL-000001")]),
                           t("TURN_2.json", [mk("book_service_visit", "EVE-PAR-LOCAL-000002")]),
                           t("TURN_3.json", [mk("pay_invoice", "EVE-PAR-LOCAL-000003")])])
    assert sorted(dets) == ["EVE-PAR-LOCAL-000001", "EVE-PAR-LOCAL-000002"]
    assert CONSEQUENTIAL_TOOLS == frozenset({"set_supplier_risk_status", "book_service_visit"})


# ================================================================ the delegation server
def test_the_supplier_app_has_no_delegation_mode():
    from eva.web.app import create_app
    import tempfile
    c = TestClient(create_app(runs_root=Path(tempfile.mkdtemp()), evidence_root=Path(tempfile.mkdtemp())))
    assert c.get("/api/mode").status_code == 404


def test_mode_and_mandate_session_without_binding(dirs):
    fake = eve("allow", CH_V1, "EVE-PAR-LOCAL-000101")
    c = client(dirs, fake)
    assert c.get("/api/mode").json()["mode"] == "delegation"
    t = turn(c, MANDATE_TEXT)
    assert not t["observed"]["booking_proposed"] and t["proposals"][0]["kind"] == "mandate_proposal"
    assert t["spoken"] == "Please confirm: Mandate: dishwasher repair, up to $200, this week. Confirm?"
    t = turn(c, "Book the repair.")                                          # no binding yet
    assert t["observed"]["gate_reason"] == "NO_OPERATOR_CHAIN_BINDING" and not t["observed"]["booked"]
    assert fake.calls == [] and c.get("/api/delegation/state").json()["bookings"] == {}


def test_confirmation_is_human_only_and_exact(dirs):
    c = client(dirs)
    turn(c, MANDATE_TEXT)
    bad = c.post("/api/delegation/confirm", json={"kind": "mandate", "read_back": "Mandate: up to $2000. Confirm?",
                                                  "confirmed_by": "J", "confirmation_utterance": "Yes."})
    assert bad.status_code == 409 and list(dirs["ev"].glob("MANDATE_*.json")) == []
    ok = confirm_pending(c)
    assert ok.status_code == 200 and ok.json()["record"]["limit_usd"] == 200
    files = list(dirs["ev"].glob("MANDATE_*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8"))["confirmed_by"] == "Joakim Eklund"
    assert c.get("/api/delegation/state").json()["pending"] == []            # a proposal confirms once
    again = c.post("/api/delegation/confirm", json={"kind": "mandate", "read_back": ok.json()["record"]["read_back"],
                                                    "confirmed_by": "J", "confirmation_utterance": "Yes."})
    assert again.status_code == 409


def _v1_session(dirs):
    """Mandate confirmed; DW-v1 taken in and bound; one booking attempt that EVE escalates."""
    c0 = client(dirs)
    turn(c0, MANDATE_TEXT)
    assert confirm_pending(c0).status_code == 200
    write_intake(dirs["intakes"], CH_V1, [GAP_V1])
    lb = lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],),
                      consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    fake = eve("escalate", CH_V1, "EVE-PAR-LOCAL-000201")
    c1 = client(dirs, fake, lb)
    return c1, fake, turn(c1, "Book the repair.")


def test_v1_escalate_books_nothing_and_is_recorded(dirs):
    c1, fake, t = _v1_session(dirs)
    o = t["observed"]
    assert o["booking_proposed"] and o["eve_called"] and o["customer_policy_outcome"] == "escalate"
    assert not o["booked"] and fake.calls[0][0] == CH_V1 and fake.calls[0][1]["price_usd"] == 275
    assert t["spoken"] == "EVE required human review. Nothing was booked. Evidence record EVE-PAR-LOCAL-000201."
    rec = load_record(dirs["ev"] / t["evidence_file"], ("eva_i4_turn",))          # self-hash verifies
    assert rec.body["policy"]["observations"][0]["result"] == "MATCH"
    assert rec.body["binding"]["bindings"] == {"book_service_visit": {OFFER: CH_V1}}
    assert c1.get("/api/delegation/state").json()["bookings"] == {}


def test_why_after_v1_is_established_from_records_only(dirs):
    c1, _, _ = _v1_session(dirs)
    a = c1.post("/api/delegation/why", json={"question": "Why didn't you book it?"}).json()
    assert a["answer_class"] == "ESTABLISHED"
    assert a["spoken"] == ("I didn't book it. The quote was $275 and your confirmed mandate allows up to $200. "
                           "EVE required human review: the approval on record does not cover this request. "
                           "Evidence record EVE-PAR-LOCAL-000201.")
    files = [s["source"]["file"] for s in a["statements"]]
    assert files[0].startswith("TURN_") and files[1].startswith("INTAKE_") and files[2].startswith("MANDATE_")
    assert "APPROVAL_SCOPE_MISMATCH" in a["statements"][1]["text"]
    assert "because" not in a["spoken"].lower()


def test_why_answer_classes(dirs):
    c = client(dirs)
    assert c.post("/api/delegation/why", json={"question": "What's the weather?"}).json()["answer_class"] == "OUT_OF_SCOPE"
    assert c.post("/api/delegation/why", json={"question": "Why didn't you book it?"}).json()["answer_class"] \
        == "NOT_ESTABLISHED"                                                    # no booking attempt recorded


def test_why_fails_closed_on_a_tampered_record(dirs):
    c1, _, _ = _v1_session(dirs)
    m = next(dirs["ev"].glob("MANDATE_*.json"))
    rec = json.loads(m.read_text(encoding="utf-8"))
    rec["limit_usd"] = 500
    m.write_text(json.dumps(rec), encoding="utf-8")
    a = c1.post("/api/delegation/why", json={"question": "Why didn't you book it?"}).json()
    assert a["answer_class"] == "SOURCE_VERIFICATION_FAILED" and a["statements"] == []


def test_why_without_a_gap_in_the_records_says_so(dirs):
    c0 = client(dirs)
    turn(c0, MANDATE_TEXT)
    confirm_pending(c0)
    write_intake(dirs["intakes"], CH_V1, [])                                 # stored intake records no gap
    lb = lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    c1 = client(dirs, eve("escalate", CH_V1, "EVE-PAR-LOCAL-000301"), lb)
    turn(c1, "Book the repair.")
    a = c1.post("/api/delegation/why", json={"question": "why did you not book it"}).json()
    assert a["answer_class"] == "ESTABLISHED" and "approval on record" not in a["spoken"]
    assert any("more specific reason" in m for m in a["not_established"])


def test_v2_after_confirmed_approval_books_once_and_history_keeps_v1(dirs):
    c1, _, _ = _v1_session(dirs)
    t = turn(c1, "$275 is fine.")
    assert t["proposals"][0]["kind"] == "authorization_proposal" and not t["observed"]["booking_proposed"]
    assert confirm_pending(c1, utterance="$275 is fine.").status_code == 200
    write_intake(dirs["intakes"], CH_V2, [], ts="20261006T130000000000Z")
    lb2 = lock_binding(write_binding(dirs["root"], CH_V2), (dirs["intakes"],), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    c2 = client(dirs, eve("allow", CH_V2, "EVE-PAR-LOCAL-000202"), lb2)          # new process, new binding (D5 B4)
    t2 = turn(c2, "Book the repair.")
    assert t2["observed"]["booked"] and t2["spoken"].startswith("EVE allowed the booking.")
    assert OFFER in c2.get("/api/delegation/state").json()["bookings"]
    h = c2.get("/api/history").json()["items"]
    by = {i["eve_record_id"]: i for i in h}
    assert by["EVE-PAR-LOCAL-000201"]["customer_policy_outcome"] == "escalate" and not by["EVE-PAR-LOCAL-000201"]["executed"]
    assert by["EVE-PAR-LOCAL-000202"]["customer_policy_outcome"] == "allow" and by["EVE-PAR-LOCAL-000202"]["executed"]
    v1 = c2.get("/api/audit/EVE-PAR-LOCAL-000201").json()
    assert v1["verification"] == "VERIFIED" and v1["export"]["evidence_chain"]["chain_id"] == CH_V1
    assert v1["export"]["determination"]["customer_policy_outcome"] == "escalate"
    a = c2.post("/api/delegation/why", json={"question": "Why didn't you book it?"}).json()
    assert a["answer_class"] == "NOT_ESTABLISHED" and "was made" in a["spoken"]


def test_policy_identity_mismatch_books_nothing(dirs):
    c0 = client(dirs)
    turn(c0, MANDATE_TEXT)
    confirm_pending(c0)
    write_intake(dirs["intakes"], CH_V1, [])
    lb = lock_binding(write_binding(dirs["root"], CH_V1), (dirs["intakes"],), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    other = {"policy_ref": config.POLICY_REF, "policy_content_sha256": "0" * 64}
    c = client(dirs, eve("allow", CH_V1, "EVE-PAR-LOCAL-000401", policy=other), lb)
    t = turn(c, "Book the repair.")
    assert not t["observed"]["booked"] and t["observed"]["gate_decision"] == "DENY"
    assert c.get("/api/delegation/state").json()["bookings"] == {}


def test_a_bound_offer_outside_the_offer_register_refuses_to_start(dirs):
    write_intake(dirs["intakes"], CH_V1, [], subject="DW-OFFER-999")
    p = dirs["root"] / "x.chain_map.json"
    p.write_text(json.dumps({"schema": "eva-chain-map-1.0", "note": "t", "bindings": {"book_service_visit":
                                                                                     {"DW-OFFER-999": CH_V1}}}))
    lb = lock_binding(p, (dirs["intakes"],), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    with pytest.raises(BindingError):
        client(dirs, eve("allow", CH_V1, "EVE-PAR-LOCAL-000501"), lb)


def test_the_page_is_the_same_file_for_both_servers(dirs):
    from eva.web.app import STATIC
    assert client(dirs).get("/").content == (STATIC / "index.html").read_bytes()


def test_d5_b5_a_binding_file_changed_after_start_stops_before_anything_runs(dirs):
    write_intake(dirs["intakes"], CH_V1, [GAP_V1])
    bpath = write_binding(dirs["root"], CH_V1)
    lb = lock_binding(bpath, (dirs["intakes"],), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS)
    fake = eve("allow", CH_V1, "EVE-PAR-LOCAL-000601")
    c = client(dirs, fake, lb)
    bpath.write_text(bpath.read_text(encoding="utf-8") + " ", encoding="utf-8")
    r = c.post("/api/delegation/turn", json={"utterance": "Book the repair.", "proposer": "scripted"})
    assert r.status_code == 503 and "STOP" in r.json()["error"]
    assert fake.calls == [] and list(dirs["ev"].glob("TURN_*.json")) == []
