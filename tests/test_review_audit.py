"""Step 6 -- review queue and audit export against decision D4 (blob 2869b55c...).

The tests try to BREAK D4: override an escalate, rewrite a review, forge a review onto an allow, use a
review as evidence, and act through HANDLED_BY_HUMAN. Every such path must fail hard.
Real committed records are used where they exist (evidence/i4, evidence/intake_live); turn records on
the new EVA-CH chains are SYNTHETIC (no EVA turn has run on those chains yet) and labelled as such.
"""
import ast
import copy
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eva import config
from eva.agent import build_agent
from eva.authorization import AuthorizationStore
from eva.gate import EveGate
from eva.scripted_model import ScriptedModel
from eva.tools import SupplierRegister, build_tools
from eva_intake import declaration as DECL
from eva_review import audit as A
from eva_review import review as R
from eva_review.records import D4_BLOB, RecordError, canonical_sha256, load_dir, load_record

REPO = Path(__file__).resolve().parent.parent
TURN_ALLOW = REPO / "evidence/i4/TURN_20260930T192518345317Z_1.json"       # real: PAR 000019 allow, executed
TURN_ESCALATE = REPO / "evidence/i4/TURN_20260930T192541253230Z_2.json"    # real: PAR 000020 escalate
INTAKE_V1 = REPO / "evidence/intake_live/INTAKE_20261002T183404278993Z_SAVE_EVA-CH-e8fcd04353baf54fab0d91d0.json"
INTAKE_V2 = REPO / "evidence/intake_live/INTAKE_20261002T183505508304Z_SAVE_EVA-CH-995bf4a9f7c53e97719380c9.json"
INTAKE_V1_PRINT = REPO / "evidence/intake_live/INTAKE_20261002T183404173779Z_PRINT_ONLY_EVA-CH-e8fcd04353baf54fab0d91d0.json"
V1, V2 = "EVA-CH-e8fcd04353baf54fab0d91d0", "EVA-CH-995bf4a9f7c53e97719380c9"
TURN_KINDS, INTAKE_KINDS, REVIEW_KINDS = ("eva_i4_turn",), ("eva_chain_intake",), ("eva_review",)
NOW = dt.datetime(2026, 10, 3, 9, 0, 0, tzinfo=dt.timezone.utc)


def turns_of(*paths):
    return [load_record(p, TURN_KINDS) for p in paths]


def intake(p):
    return load_record(p, INTAKE_KINDS)


def synthetic_turn(path, *, seq, chain_id, par, cpo, vco, decision, executed, supplier="SUP-EPSILON-001",
                   status="high", before="medium"):
    """A turn record in the eva_i4_turn schema. SYNTHETIC: no EVA turn has run on the EVA-CH chains yet."""
    tid = f"synthetic-tu-{seq}"
    after = status if executed else before
    rec = {"record_kind": "eva_i4_turn", "record_schema_version": "eva-i4-turn-1.0", "synthetic": True,
           "turn_seq": seq, "turn_utc": f"20261003T0900{seq:02d}000000Z", "utterance": f"Raise {supplier} to {status}",
           "eve": {"bearer": "PRESENT_NOT_RECORDED", "policy_ref": "eve-mcp-demo-policy-v1"},
           "proposer": {"kind": "scripted", "label": "Scripted proposer (no LLM)"},
           "gate_decisions": [{"args": {"risk_status": status, "supplier_id": supplier}, "chain_id": chain_id,
                               "customer_policy_outcome": cpo, "decision": decision, "eve_called": True,
                               "eve_record_id": par, "pre_action_status": "evaluated", "reason": f"EVE_OUTCOME: {cpo}",
                               "tool_name": "set_supplier_risk_status", "tool_use_id": tid,
                               "verified_chain_outcome": vco}],
           "tool_executions": ([{"chain_id": chain_id, "eve_record_id": par, "executed": True, "new": status,
                                 "old": before, "supplier_id": supplier, "tool_use_id": tid}] if executed else []),
           "register": {"before_sha256": "b" * 64, "after_sha256": ("a" if executed else "b") * 64,
                        "changed": executed}}
    rec["record_sha256"] = canonical_sha256(rec)
    Path(path).write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_record(path, TURN_KINDS)


def reviews(d):
    return load_dir(d, "REVIEW_*.json", REVIEW_KINDS)


# ------------------------------------------------------------------ the queue

def test_queue_holds_exactly_the_unexecuted_escalate_from_the_real_records():
    q = R.queue(turns_of(TURN_ALLOW, TURN_ESCALATE), [])
    assert [i["eve_record_id"] for i in q] == ["EVE-PAR-LOCAL-000020"]
    assert q[0]["chain_id"] == "EVE-MCP-DEMO-B-2026-001" and q[0]["executed"] is False


def test_a_review_closes_the_item_and_is_written_once(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    path, body = R.write_review(tmp_path, turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="DECLINED",
                                reviewer="Operator (test)", note="not now", now=NOW)
    assert body["decision_d4_blob"] == D4_BLOB and body["effects"]["authorizes_action"] is False
    assert R.queue(turns, reviews(tmp_path)) == []
    before = path.read_bytes()
    for outcome in R.OUTCOMES:
        with pytest.raises(R.ReviewError) as e:
            R.write_review(tmp_path, turns, reviews(tmp_path), eve_record_id="EVE-PAR-LOCAL-000020", outcome=outcome,
                           reviewer="Someone else", note="change it", now=NOW + dt.timedelta(seconds=1),
                           intake=intake(INTAKE_V1) if outcome == "NEW_EVIDENCE" else None)
        assert e.value.code == "REVIEW_EXISTS"
    assert path.read_bytes() == before and len(list(tmp_path.iterdir())) == 1


# ------------------------------------------------------------------ attempts to break D4

@pytest.mark.parametrize("outcome", ["ALLOW", "APPROVE", "APPROVE_AND_EXECUTE", "EXECUTE", "allow", "OVERRIDE", ""])
def test_no_outcome_can_authorise_or_override(tmp_path, outcome):
    with pytest.raises(R.ReviewError) as e:
        R.write_review(tmp_path, turns_of(TURN_ALLOW, TURN_ESCALATE), [], eve_record_id="EVE-PAR-LOCAL-000020",
                       outcome=outcome, reviewer="Operator (test)", note="", now=NOW)
    assert e.value.code == "INVALID_OUTCOME" and list(tmp_path.iterdir()) == []


def test_an_allow_or_unknown_determination_cannot_be_reviewed(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    for par, code in (("EVE-PAR-LOCAL-000019", "NOT_A_REVIEW_ITEM"), ("EVE-PAR-LOCAL-999999", "UNKNOWN_PAR")):
        with pytest.raises(R.ReviewError) as e:
            R.write_review(tmp_path, turns, [], eve_record_id=par, outcome="DECLINED", reviewer="Operator (test)",
                           note="", now=NOW)
        assert e.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_an_edited_review_record_is_refused(tmp_path):
    path, _ = R.write_review(tmp_path, turns_of(TURN_ALLOW, TURN_ESCALATE), [], eve_record_id="EVE-PAR-LOCAL-000020",
                             outcome="DECLINED", reviewer="Operator (test)", note="", now=NOW)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["outcome"] = "HANDLED_BY_HUMAN"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecordError) as e:
        reviews(tmp_path)
    assert e.value.code == "RECORD_TAMPERED"


def test_a_forged_review_moved_onto_an_allow_is_caught_by_the_export(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    path, body = R.write_review(tmp_path, turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="DECLINED",
                                reviewer="Operator (test)", note="", now=NOW)
    forged = copy.deepcopy(body)
    forged["reviewed"]["eve_record_id"] = "EVE-PAR-LOCAL-000019"
    del forged["record_sha256"]
    forged["record_sha256"] = canonical_sha256(forged)               # an attacker can re-hash; the export still refuses
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(A.AuditError) as e:
        A.export_action("EVE-PAR-LOCAL-000019", turns, [], reviews(tmp_path))
    assert e.value.code == "REVIEW_OF_NON_ESCALATE"


def test_two_reviews_for_one_determination_are_refused_everywhere(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    path, body = R.write_review(tmp_path, turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="DECLINED",
                                reviewer="Operator (test)", note="", now=NOW)
    shutil.copyfile(path, tmp_path / "REVIEW_20991231T000000000000Z_EVE-PAR-LOCAL-000020.json")
    with pytest.raises(R.ReviewError) as e:
        R.queue(turns, reviews(tmp_path))
    assert e.value.code == "DUPLICATE_REVIEW"
    with pytest.raises(A.AuditError) as e:
        A.export_action("EVE-PAR-LOCAL-000020", turns, [], reviews(tmp_path))
    assert e.value.code == "DUPLICATE_REVIEW"


def test_a_review_record_is_never_evidence(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    path, body = R.write_review(tmp_path / "r", turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="DECLINED",
                                reviewer="Operator (test)", note="", now=NOW)
    with pytest.raises(DECL.DeclarationError):                        # the intake refuses a review as a declaration
        DECL.validate(body, authorisation_statuses=frozenset({"authorised"}), monitoring_statuses=frozenset({"monitored"}))
    with pytest.raises(R.ReviewError) as e:                           # and a review cannot be cited as new evidence
        R.write_review(tmp_path / "r2", turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="NEW_EVIDENCE",
                       reviewer="Operator (test)", note="", intake=load_record(path, REVIEW_KINDS), now=NOW)
    assert e.value.code == "NEW_EVIDENCE_NOT_AN_INTAKE"


def test_new_evidence_must_be_a_stored_different_chain_for_the_same_action(tmp_path):
    t = synthetic_turn(tmp_path / "TURN_x_1.json", seq=1, chain_id=V2, par="EVE-PAR-SYN-000101", cpo="escalate",
                       vco="HUMAN_REVIEW_REQUIRED", decision="DENY", executed=False)
    other = synthetic_turn(tmp_path / "TURN_x_2.json", seq=2, chain_id=V2, par="EVE-PAR-SYN-000102", cpo="escalate",
                           vco="HUMAN_REVIEW_REQUIRED", decision="DENY", executed=False, supplier="SUP-ZETA-002")
    cases = [("EVE-PAR-SYN-000101", "NEW_EVIDENCE", None, "NEW_EVIDENCE_REQUIRES_INTAKE"),
             ("EVE-PAR-SYN-000101", "NEW_EVIDENCE", intake(INTAKE_V2), "NEW_EVIDENCE_SAME_CHAIN"),
             ("EVE-PAR-SYN-000101", "NEW_EVIDENCE", intake(INTAKE_V1_PRINT), "NEW_EVIDENCE_NOT_STORED"),
             ("EVE-PAR-SYN-000102", "NEW_EVIDENCE", intake(INTAKE_V1), "NEW_EVIDENCE_OTHER_ACTION"),
             ("EVE-PAR-SYN-000101", "DECLINED", intake(INTAKE_V1), "INTAKE_NOT_ALLOWED"),
             ("EVE-PAR-SYN-000101", "HANDLED_BY_HUMAN", intake(INTAKE_V1), "INTAKE_NOT_ALLOWED")]
    for par, outcome, ik, code in cases:
        with pytest.raises(R.ReviewError) as e:
            R.write_review(tmp_path / "reviews", [t, other], [], eve_record_id=par, outcome=outcome,
                           reviewer="Operator (test)", note="", intake=ik, now=NOW)
        assert e.value.code == code, (outcome, code)
    assert not (tmp_path / "reviews").exists()


def test_an_execution_without_allow_is_an_invariant_violation(tmp_path):
    bad = synthetic_turn(tmp_path / "TURN_bad_1.json", seq=1, chain_id=V2, par="EVE-PAR-SYN-000201", cpo="escalate",
                         vco="HUMAN_REVIEW_REQUIRED", decision="DENY", executed=True)
    with pytest.raises(R.ReviewError) as e:
        R.queue([bad], [])
    assert e.value.code == "INVARIANT_EXECUTED_WITHOUT_ALLOW"
    with pytest.raises(A.AuditError) as e:
        A.export_action("EVE-PAR-SYN-000201", [bad], [], [])
    assert e.value.code == "INVARIANT_EXECUTED_WITHOUT_ALLOW"


def test_handled_by_human_executes_nothing_and_the_gate_still_denies(tmp_path):
    turns = turns_of(TURN_ALLOW, TURN_ESCALATE)
    R.write_review(tmp_path / "reviews", turns, [], eve_record_id="EVE-PAR-LOCAL-000020", outcome="HANDLED_BY_HUMAN",
                   reviewer="Operator (test)", note="changed by hand in the source system", now=NOW)
    reg_path = tmp_path / "supplier_register.json"
    shutil.copyfile(config.DATA_DIR / "supplier_register_seed.json", reg_path)
    register = SupplierRegister(reg_path)
    before = reg_path.read_bytes()

    class EscalatingEve:
        async def __call__(self, chain_id, action_context):
            return {"isError": False, "structuredContent": {
                "eve": {"chain_id": chain_id, "pre_action_status": "evaluated", "customer_policy_outcome": "escalate",
                        "verified_chain_outcome": "HUMAN_REVIEW_REQUIRED"}, "eve_record_id": "EVE-PAR-LOCAL-000999"}}

    store, executions = AuthorizationStore(), []
    gate = EveGate(EscalatingEve(), store, chain_map={"set_supplier_risk_status": {"SUP-ZETA-002": "EVE-MCP-DEMO-B-2026-001"}})
    agent = build_agent(ScriptedModel([("tool", "tu-1", "set_supplier_risk_status",
                                        {"supplier_id": "SUP-ZETA-002", "risk_status": "high"}), ("text", "done")]),
                        gate, build_tools(store, register, executions))
    agent("go")
    assert gate.decisions[-1].decision == "DENY" and executions == [] and reg_path.read_bytes() == before

    export = A.export_action("EVE-PAR-LOCAL-000020", turns, [], reviews(tmp_path / "reviews"))
    assert export["determination"]["customer_policy_outcome"] == "escalate"
    assert export["review"]["outcome"] == "HANDLED_BY_HUMAN"
    assert export["review"]["effects"]["eva_execution"] == "NONE" and export["execution"]["executed_by_eva"] is False


def test_review_package_has_no_path_to_execution():
    forbidden = ("eva.tools", "eva.gate", "eva.authorization", "eva.agent", "eva.cli", "eva.web", "strands")
    for py in (REPO / "eva_review").glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in names if m.startswith(forbidden)], py.name


# ------------------------------------------------------------------ the export and the central invariant

def test_export_states_missing_links_explicitly():
    e = A.export_action("EVE-PAR-LOCAL-000020", turns_of(TURN_ALLOW, TURN_ESCALATE), [], [])
    assert e["evidence_chain"]["lineage"].startswith("NOT_ESTABLISHED")
    assert e["policy"]["policy_ref"] == "eve-mcp-demo-policy-v1"
    assert e["policy"]["policy_content_sha256"].startswith("NOT_ESTABLISHED")
    assert e["review"] == "NONE_RECORDED" and e["determination"]["customer_policy_outcome"] == "escalate"
    a = A.export_action("EVE-PAR-LOCAL-000019", turns_of(TURN_ALLOW, TURN_ESCALATE), [], [])
    assert a["review"].startswith("NOT_APPLICABLE") and a["execution"]["executed_by_eva"] is True


def test_review_changes_the_future_evidence_state_never_historical_truth(tmp_path):
    """v2 (approval withdrawn) escalates; the review cites NEW evidence (v1 complete, real intake record);
    the new chain is evaluated and allowed. The original escalate, its turn record and its export stay true."""
    t_old = synthetic_turn(tmp_path / "TURN_flow_1.json", seq=1, chain_id=V2, par="EVE-PAR-SYN-000301",
                           cpo="escalate", vco="HUMAN_REVIEW_REQUIRED", decision="DENY", executed=False)
    old_bytes = (tmp_path / "TURN_flow_1.json").read_bytes()
    intakes = [intake(INTAKE_V1), intake(INTAKE_V2)]
    before = A.export_action("EVE-PAR-SYN-000301", [t_old], intakes, [])

    R.write_review(tmp_path / "reviews", [t_old], [], eve_record_id="EVE-PAR-SYN-000301", outcome="NEW_EVIDENCE",
                   reviewer="Operator (test)", note="approval re-issued", intake=intake(INTAKE_V1), now=NOW)
    t_new = synthetic_turn(tmp_path / "TURN_flow_2.json", seq=2, chain_id=V1, par="EVE-PAR-SYN-000302",
                           cpo="allow", vco="ACTION_CHAIN_SUPPORTED", decision="ALLOW", executed=True)
    turns, revs = [t_old, t_new], reviews(tmp_path / "reviews")
    after = A.export_action("EVE-PAR-SYN-000301", turns, intakes, revs)
    new = A.export_action("EVE-PAR-SYN-000302", turns, intakes, revs)

    assert (tmp_path / "TURN_flow_1.json").read_bytes() == old_bytes            # historical record untouched
    assert after["determination"] == before["determination"]                     # historical determination unchanged
    assert after["determination"]["customer_policy_outcome"] == "escalate"
    assert after["execution"]["executed_by_eva"] is False                        # the old action never ran
    assert after["evidence_chain"]["lineage"]["supersedes"] == V1                 # v2's recorded succession (real)
    ne = after["review"]["new_evidence"]
    assert ne["new_chain_id"] == V1 and ne["later_determinations_on_new_chain"][0]["eve_record_id"] == "EVE-PAR-SYN-000302"
    assert new["determination"]["customer_policy_outcome"] == "allow" and new["execution"]["executed_by_eva"] is True
    assert new["review"].startswith("NOT_APPLICABLE")                            # the allow came from EVE, not the review

    files = {p.name: p.read_bytes() for p in [*tmp_path.glob("TURN_*.json"), *(tmp_path / "reviews").glob("*.json"),
                                              INTAKE_V1, INTAKE_V2]}
    A.verify_export(after, files)
    A.verify_export(new, files)


def test_export_verification_detects_any_change(tmp_path):
    shutil.copyfile(TURN_ESCALATE, tmp_path / TURN_ESCALATE.name)
    turns = turns_of(TURN_ALLOW, tmp_path / TURN_ESCALATE.name)
    e = A.export_action("EVE-PAR-LOCAL-000020", turns, [], [])
    files = {TURN_ESCALATE.name: (tmp_path / TURN_ESCALATE.name).read_bytes()}
    A.verify_export(e, files)
    with pytest.raises(A.AuditError) as x:
        A.verify_export(e, {TURN_ESCALATE.name: files[TURN_ESCALATE.name] + b" "})
    assert x.value.code == "SOURCE_CHANGED"
    changed = copy.deepcopy(e)
    changed["determination"]["customer_policy_outcome"] = "allow"
    with pytest.raises(A.AuditError) as x:
        A.verify_export(changed, files)
    assert x.value.code == "EXPORT_TAMPERED"


# ------------------------------------------------------------------ command line

def test_cli_queue_review_export_and_stop(tmp_path, capsys):
    from eva_review.__main__ import main
    tdir = tmp_path / "turns"
    tdir.mkdir()
    for p in (TURN_ALLOW, TURN_ESCALATE):
        shutil.copyfile(p, tdir / p.name)
    rdir, out = tmp_path / "reviews", tmp_path / "exports"
    assert main(["queue", "--turns", str(tdir), "--reviews", str(rdir)]) == 0
    assert "EVE-PAR-LOCAL-000020" in capsys.readouterr().out
    assert main(["review", "--turns", str(tdir), "--reviews", str(rdir), "--par", "EVE-PAR-LOCAL-000020",
                 "--outcome", "ALLOW", "--reviewer", "Operator (test)"]) == 2
    assert "INVALID_OUTCOME" in capsys.readouterr().out and not rdir.exists()
    assert main(["review", "--turns", str(tdir), "--reviews", str(rdir), "--par", "EVE-PAR-LOCAL-000020",
                 "--outcome", "DECLINED", "--reviewer", "Operator (test)"]) == 0
    assert main(["queue", "--turns", str(tdir), "--reviews", str(rdir)]) == 0
    assert "0 open review item(s)" in capsys.readouterr().out
    assert main(["export", "--turns", str(tdir), "--reviews", str(rdir), "--par", "EVE-PAR-LOCAL-000020",
                 "--out", str(out)]) == 0
    (exp,) = list(out.glob("AUDIT_*.json"))
    bundle = json.loads(exp.read_text(encoding="utf-8"))
    files = {p.name: p.read_bytes() for p in [*tdir.glob("*.json"), *rdir.glob("*.json")]}
    A.verify_export(bundle, files)
    assert bundle["review"]["outcome"] == "DECLINED" and bundle["determination"]["customer_policy_outcome"] == "escalate"
    (tdir / TURN_ESCALATE.name).write_bytes((tdir / TURN_ESCALATE.name).read_bytes().replace(b'"escalate"', b'"allow"', 1))
    assert main(["export", "--turns", str(tdir), "--reviews", str(rdir), "--par", "EVE-PAR-LOCAL-000020",
                 "--out", str(out)]) == 2
    assert "RECORD_TAMPERED" in capsys.readouterr().out
