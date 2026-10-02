"""Step 4 (M1-M4) against decision D5 (blob a23ae05d...). The tests try to BREAK D5.

EVE is a fake here (no network); the bindings and intake records are the real committed ones:
bindings/epsilon_v1|v2.chain_map.json and evidence/intake_live (live intake run 2026-10-02).
"""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from eva import config
from eva.binding import BindingError, lock_binding
from eva.frozen import FROZEN_I3A_BOUNDARY, verify_frozen_boundary
from eva.gate import load_chain_map
from eva.web import app as webapp
from eva_intake import declaration as DECL
from eva_review import audit as A
from eva_review.records import INTAKE_RECORD_GLOB, RecordError, canonical_sha256, load_dir, load_record

REPO = Path(__file__).resolve().parent.parent
INTAKES = REPO / "evidence" / "intake_live"
B_V1 = REPO / "bindings" / "epsilon_v1.chain_map.json"
B_V2 = REPO / "bindings" / "epsilon_v2.chain_map.json"
V1, V2 = "EVA-CH-e8fcd04353baf54fab0d91d0", "EVA-CH-995bf4a9f7c53e97719380c9"
P = {"policy_ref": config.POLICY_REF, "policy_content_sha256": config.POLICY_CONTENT_SHA256}
OUTCOME = {V1: ("allow", "ACTION_CHAIN_SUPPORTED"), V2: ("escalate", "HUMAN_REVIEW_REQUIRED"),
           "EVE-MCP-DEMO-A-2026-001": ("allow", "ACTION_CHAIN_SUPPORTED")}


class FakeEve:
    """Answers like EVE MCP v1, including structuredContent.policy. Counts calls."""
    def __init__(self, policy=P, answer_for=None, records=None):
        self.policy, self.answer_for, self.calls = policy, answer_for, []
        self.n = 0

    async def __call__(self, chain_id, action_context):
        self.calls.append(chain_id)
        self.n += 1
        cpo, vco = OUTCOME.get(chain_id, ("block", "INSUFFICIENT"))
        sc = {"eve": {"chain_id": self.answer_for or chain_id, "pre_action_status": "evaluated",
                      "customer_policy_outcome": cpo, "verified_chain_outcome": vco},
              "eve_record_id": f"EVE-PAR-TEST-{self.n:06d}"}
        if self.policy is not None:
            sc["policy"] = dict(self.policy)
        return {"isError": False, "structuredContent": sc}


def copy_binding(src, tmp_path):
    p = tmp_path / src.name
    shutil.copyfile(src, p)
    return p


def client(tmp_path, binding_path, fake, expected=P, ev="ev", runs="runs"):
    locked = lock_binding(binding_path, (INTAKES,)) if binding_path else None
    app = webapp.create_app(pre_action=fake, runs_root=tmp_path / runs, evidence_root=tmp_path / ev,
                            binding=locked, expected_policy=expected)
    return TestClient(app)


def turn(c, utterance):
    r = c.post("/api/turn", json={"utterance": utterance, "proposer": "scripted"})
    return r


def turn_records(d):
    return load_dir(d, "TURN_*.json", ("eva_i4_turn",))


# ------------------------------------------------------------------ M1: locking and the intake tie (B2, B3, B7)

def test_the_real_bindings_lock_against_the_real_intake_records():
    for path, chain in ((B_V1, V1), (B_V2, V2)):
        b = lock_binding(path, (INTAKES,))
        assert b.source == "external" and b.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert b.bindings == {"set_supplier_risk_status": {"SUP-EPSILON-001": chain}} == load_chain_map(path)
        assert [r["chain_id"] for r in b.intake_records] == [chain]


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["bindings"]["set_supplier_risk_status"].update({"SUP-EPSILON-001": "EVA-CH-000000000000000000000000"}), "BINDING_WITHOUT_INTAKE"),
    (lambda d: d["bindings"]["set_supplier_risk_status"].update({"SUP-ZETA-002": V1}), "BINDING_SUBJECT_MISMATCH"),
    (lambda d: d["bindings"].update({"get_supplier": {"SUP-EPSILON-001": V1}}), "BINDING_INVALID"),
    (lambda d: d.update({"schema": "eva-chain-map-2.0"}), "BINDING_INVALID"),
    (lambda d: d.update({"override": True}), "BINDING_INVALID"),
    (lambda d: d["bindings"].update({"set_supplier_risk_status": {}}), "BINDING_INVALID"),
])
def test_a_binding_that_does_not_select_established_evidence_refuses_to_start(tmp_path, mutate, code):
    d = json.loads(B_V1.read_text(encoding="utf-8"))
    mutate(d)
    p = tmp_path / "bad.chain_map.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(BindingError) as e:
        lock_binding(p, (INTAKES,))
    assert e.value.code == code


def test_the_intake_directory_with_its_run_index_reads_only_intake_records():
    names = sorted(p.name for p in INTAKES.glob(INTAKE_RECORD_GLOB))
    assert len(names) == 4 and all(n.startswith("INTAKE_2") for n in names)
    assert (INTAKES / "INTAKE_LIVE_RUN_INDEX_2026-10-02.json").is_file()          # present, and not matched
    assert all(r.body["record_kind"] == "eva_chain_intake"
               for r in load_dir(INTAKES, INTAKE_RECORD_GLOB, ("eva_chain_intake",)))


def test_without_intake_records_an_eva_chain_cannot_be_bound(tmp_path):
    with pytest.raises(BindingError) as e:
        lock_binding(B_V1, ())
    assert e.value.code == "BINDING_WITHOUT_INTAKE"


def test_a_tampered_intake_record_cannot_back_a_binding(tmp_path):
    d = tmp_path / "intakes"
    shutil.copytree(INTAKES, d)
    f = next(d.glob("INTAKE_*_SAVE_EVA-CH-e8fcd*.json"))
    rec = json.loads(f.read_text(encoding="utf-8"))
    rec["subject_ref"] = "SUP-ZETA-002"
    f.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(RecordError) as e:
        lock_binding(B_V1, (d,))
    assert e.value.code == "RECORD_TAMPERED"


def test_a_binding_is_never_evidence(tmp_path):
    raw = json.loads(B_V1.read_text(encoding="utf-8"))
    with pytest.raises(DECL.DeclarationError):
        DECL.validate(raw, authorisation_statuses=frozenset({"authorised"}), monitoring_statuses=frozenset({"monitored"}))
    with pytest.raises(RecordError):
        load_record(B_V1, ("eva_chain_intake",))


# ------------------------------------------------------------------ the end-to-end invariant

def test_v1_allow_v2_escalate_and_v1_stays_attributable_to_binding_v1_chain_v1_policy_p(tmp_path):
    fake = FakeEve()
    c1 = client(tmp_path, copy_binding(B_V1, tmp_path), fake, ev="ev", runs="runs1")
    r1 = turn(c1, "Raise Epsilon to high")
    assert r1.status_code == 200
    t1 = r1.json()
    assert t1["observed"]["gate_decision"] == "ALLOW" and t1["observed"]["tool_executed"] is True
    rec1_path = tmp_path / "ev" / t1["evidence_file"]
    rec1_bytes = rec1_path.read_bytes()

    c2 = client(tmp_path, copy_binding(B_V2, tmp_path), fake, ev="ev", runs="runs2")    # a new process (B6)
    t2 = turn(c2, "Raise Epsilon to critical").json()
    assert t2["observed"]["gate_decision"] == "DENY" and t2["observed"]["tool_executed"] is False
    assert t2["observed"]["customer_policy_outcome"] == "escalate" and t2["register"]["changed"] is False
    assert fake.calls == [V1, V2]

    assert rec1_path.read_bytes() == rec1_bytes                      # the earlier turn record is untouched
    turns = turn_records(tmp_path / "ev")
    intakes = load_dir(INTAKES, INTAKE_RECORD_GLOB, ("eva_chain_intake",))
    e1 = A.export_action(t1["gate_decisions"][0]["eve_record_id"], turns, intakes, [])
    e2 = A.export_action(t2["gate_decisions"][0]["eve_record_id"], turns, intakes, [])
    assert e1["evidence_chain"]["chain_id"] == V1 and e2["evidence_chain"]["chain_id"] == V2
    assert e1["evidence_chain"]["binding"]["sha256"] == hashlib.sha256(B_V1.read_bytes()).hexdigest()
    assert e2["evidence_chain"]["binding"]["sha256"] == hashlib.sha256(B_V2.read_bytes()).hexdigest()
    assert e1["evidence_chain"]["lineage"]["declaration_sha256"] != e2["evidence_chain"]["lineage"]["declaration_sha256"]
    assert e2["evidence_chain"]["lineage"]["supersedes"] == V1
    for e in (e1, e2):
        assert e["policy"]["policy_content_sha256"] == config.POLICY_CONTENT_SHA256
        assert e["policy"]["observed_against_locked"] == "MATCH"
    assert e1["determination"]["customer_policy_outcome"] == "allow" and e1["execution"]["executed_by_eva"] is True
    assert e2["determination"]["customer_policy_outcome"] == "escalate" and e2["execution"]["executed_by_eva"] is False
    files = {p.name: p.read_bytes() for p in [*(tmp_path / "ev").glob("TURN_*.json"), *INTAKES.glob(INTAKE_RECORD_GLOB)]}
    A.verify_export(e1, files)
    A.verify_export(e2, files)


# ------------------------------------------------------------------ M2: locked per process (B4, B5, B6)

def test_a_hot_swapped_binding_is_a_stop_before_any_action(tmp_path):
    fake = FakeEve()
    bpath = copy_binding(B_V1, tmp_path)
    c = client(tmp_path, bpath, fake)
    assert turn(c, "Raise Epsilon to high").json()["observed"]["tool_executed"] is True
    shutil.copyfile(B_V2, bpath)                                      # operator swaps the file under a running process
    before = {p.name: p.read_bytes() for p in (tmp_path / "ev").glob("TURN_*.json")}
    r = turn(c, "Raise Epsilon to critical")
    assert r.status_code == 503 and "BINDING_CHANGED" in r.json()["error"]
    assert fake.calls == [V1]                                          # EVE was not asked again; nothing ran
    assert {p.name: p.read_bytes() for p in (tmp_path / "ev").glob("TURN_*.json")} == before
    (stop,) = list((tmp_path / "ev").glob("STOP_*.json"))
    s = json.loads(stop.read_text(encoding="utf-8"))
    assert s["stop"]["code"] == "BINDING_CHANGED" and s["action"] == "NONE"
    assert s["binding_locked"]["sha256"] == hashlib.sha256(B_V1.read_bytes()).hexdigest()


def test_a_removed_binding_file_is_a_stop(tmp_path):
    fake = FakeEve()
    bpath = copy_binding(B_V1, tmp_path)
    c = client(tmp_path, bpath, fake)
    bpath.unlink()
    r = turn(c, "Raise Epsilon to high")
    assert r.status_code == 503 and "BINDING_UNREADABLE" in r.json()["error"] and fake.calls == []


def test_every_turn_carries_the_locked_binding_and_the_observed_policy(tmp_path):
    c = client(tmp_path, copy_binding(B_V1, tmp_path), FakeEve())
    t = turn(c, "Raise Epsilon to high").json()
    assert t["record_schema_version"] == "eva-i4-turn-1.1"
    assert t["binding"]["source"] == "external" and t["binding"]["file"] == B_V1.name
    assert t["binding"]["bindings"] == {"set_supplier_risk_status": {"SUP-EPSILON-001": V1}}
    (obs,) = t["policy"]["observations"]
    assert obs["observed"] == P and obs["expected"] == P and obs["result"] == "MATCH"


def test_an_unbound_supplier_and_a_chain_mismatch_are_denied_by_the_gate(tmp_path):
    fake = FakeEve()
    c = client(tmp_path, copy_binding(B_V1, tmp_path), fake)
    t = turn(c, "Raise Zeta to high").json()                          # Zeta is not in the v1 binding
    assert t["observed"]["gate_decision"] == "DENY" and "NO_OPERATOR_CHAIN_BINDING" in t["observed"]["gate_reason"]
    assert fake.calls == []
    liar = FakeEve(answer_for=V2)                                      # EVE answers for another chain (B9)
    c2 = client(tmp_path, copy_binding(B_V1, tmp_path), liar, ev="ev2", runs="runs2")
    t2 = turn(c2, "Raise Epsilon to high").json()
    assert t2["observed"]["gate_decision"] == "DENY" and "CHAIN_MISMATCH" in t2["observed"]["gate_reason"]
    assert t2["observed"]["tool_executed"] is False


# ------------------------------------------------------------------ M4: observed policy identity (B12, B13)

@pytest.mark.parametrize("policy", [
    {"policy_ref": config.POLICY_REF, "policy_content_sha256": "0" * 64},
    {"policy_ref": "another-policy", "policy_content_sha256": config.POLICY_CONTENT_SHA256},
    None,
])
def test_a_policy_identity_mismatch_means_no_action_and_the_observation_is_kept(tmp_path, policy):
    c = client(tmp_path, copy_binding(B_V1, tmp_path), FakeEve(policy=policy))
    t = turn(c, "Raise Epsilon to high").json()
    assert t["observed"]["tool_executed"] is False and t["register"]["changed"] is False
    (obs,) = t["policy"]["observations"]
    assert obs["result"] == "MISMATCH" and obs["expected"] == P
    assert obs["observed"] == (dict(policy) if policy else None)     # recorded as observed, never replaced


def test_without_a_locked_expectation_the_observation_is_still_recorded_not_looked_up(tmp_path):
    seen = {"policy_ref": "operator-x", "policy_content_sha256": "f" * 64}
    c = client(tmp_path, copy_binding(B_V1, tmp_path), FakeEve(policy=seen), expected=None)
    t = turn(c, "Raise Epsilon to high").json()
    (obs,) = t["policy"]["observations"]
    assert obs["observed"] == seen and obs["result"] == "NOT_COMPARED"
    assert obs["observed"]["policy_content_sha256"] != config.POLICY_CONTENT_SHA256


# ------------------------------------------------------------------ provenance cannot be rewritten

def test_turn_provenance_cannot_be_rewritten(tmp_path):
    c = client(tmp_path, copy_binding(B_V1, tmp_path), FakeEve())
    t = turn(c, "Raise Epsilon to high").json()
    path = tmp_path / "ev" / t["evidence_file"]
    rec = json.loads(path.read_text(encoding="utf-8"))
    edited = copy.deepcopy(rec)
    edited["binding"]["sha256"] = hashlib.sha256(B_V2.read_bytes()).hexdigest()
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(RecordError) as e:
        turn_records(tmp_path / "ev")
    assert e.value.code == "RECORD_TAMPERED"
    forged = copy.deepcopy(rec)                                        # re-hashed so the self-hash verifies
    forged["binding"]["bindings"] = {"set_supplier_risk_status": {"SUP-EPSILON-001": V2}}
    del forged["record_sha256"]
    forged["record_sha256"] = canonical_sha256(forged)
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(A.AuditError) as e:
        A.export_action(t["gate_decisions"][0]["eve_record_id"], turn_records(tmp_path / "ev"), [], [])
    assert e.value.code == "BINDING_DECISION_MISMATCH"


# ------------------------------------------------------------------ default unchanged (B10, B11)

def test_without_an_external_binding_the_frozen_map_applies_exactly_as_before(tmp_path):
    b = lock_binding(None)
    assert b.source == "frozen_default" and b.bindings == load_chain_map()
    assert b.sha256 == FROZEN_I3A_BOUNDARY["eva/data/chain_map.json"]
    fake = FakeEve()
    c = client(tmp_path, None, fake)
    t = turn(c, "Raise Epsilon to high").json()
    assert fake.calls == ["EVE-MCP-DEMO-A-2026-001"] and t["observed"]["gate_decision"] == "ALLOW"
    assert t["binding"]["source"] == "frozen_default"
    verify_frozen_boundary()


def test_main_requires_an_evidence_directory_with_a_binding():
    with pytest.raises(SystemExit) as e:
        webapp.main(["--binding", str(B_V1), "--intakes", str(INTAKES)])
    assert e.value.code == 2
