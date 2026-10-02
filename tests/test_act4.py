"""Act 4 UI (review + audit view) against D4 (blob 2869b55c...) and D5 (blob a23ae05d...).

The view must add no semantics: it may only show verified records and write one review record with
DECLINED or HANDLED_BY_HUMAN. The tests try to break that, and the three UI invariants:
UI-1 absence is visible, UI-2 historical ordering, UI-3 verification failure is visible.
"""
import json
import os
import re
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from eva import config
from eva.binding import lock_binding
from eva.web import act4
from eva.web import app as webapp

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "evidence" / "demo_live"
I4 = REPO / "evidence" / "i4"
INTAKES = REPO / "evidence" / "intake_live"
B_V1 = REPO / "bindings" / "epsilon_v1.chain_map.json"
B_V2 = REPO / "bindings" / "epsilon_v2.chain_map.json"
V1, V2 = "EVA-CH-e8fcd04353baf54fab0d91d0", "EVA-CH-995bf4a9f7c53e97719380c9"
P = {"policy_ref": config.POLICY_REF, "policy_content_sha256": config.POLICY_CONTENT_SHA256}
OUTCOME = {V1: ("allow", "ACTION_CHAIN_SUPPORTED"), V2: ("escalate", "HUMAN_REVIEW_REQUIRED")}


class FakeEve:
    def __init__(self):
        self.calls, self.n = [], 0

    async def __call__(self, chain_id, action_context):
        self.calls.append(chain_id)
        self.n += 1
        cpo, vco = OUTCOME[chain_id]
        return {"isError": False, "structuredContent": {
            "eve": {"chain_id": chain_id, "pre_action_status": "evaluated",
                    "customer_policy_outcome": cpo, "verified_chain_outcome": vco},
            "eve_record_id": f"EVE-PAR-TEST-{self.n:06d}", "policy": dict(P)}}


def copy_demo(tmp_path):
    d = tmp_path / "demo_live"
    shutil.copytree(DEMO, d)
    return d


def demo_client(ev, fake=None, review_enabled=True, tmp_path=None):
    app = webapp.create_app(pre_action=fake or FakeEve(), runs_root=(tmp_path or ev.parent) / "runs",
                            evidence_root=ev, intake_dirs=(INTAKES,), review_enabled=review_enabled,
                            binding=lock_binding(B_V2, (INTAKES,)), expected_policy=P)
    return TestClient(app)


def snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ the real run, as a human sees it

def test_history_of_the_real_run_shows_v1_and_v2_in_record_order():
    h = act4.history(DEMO, (INTAKES,))
    ids = [i["eve_record_id"] for i in h["items"]]
    assert ids == ["EVE-PAR-LOCAL-000024", "EVE-PAR-LOCAL-000025"]
    v1, v2 = h["items"]
    assert (v1["chain_id"], v1["customer_policy_outcome"], v1["executed"], v1["risk_before"], v1["risk_after"]) == \
        (V1, "allow", True, "medium", "high")
    assert v1["review"] is None and v1["requires_review"] is False
    assert (v2["chain_id"], v2["customer_policy_outcome"], v2["executed"]) == (V2, "escalate", False)
    assert v2["review"]["outcome"] == "DECLINED" and v2["review"]["note"] == act4.REVIEW_NOTE


def test_audit_of_the_real_run_is_verified_and_d4_is_visible():
    a1 = act4.audit_view(DEMO, (INTAKES,), "EVE-PAR-LOCAL-000024")
    a2 = act4.audit_view(DEMO, (INTAKES,), "EVE-PAR-LOCAL-000025")
    for a in (a1, a2):
        assert a["verification"] == "VERIFIED"
        pc = a["policy_comparison"]
        assert pc["observed"] == P and pc["expected"] == P and pc["result"] == "MATCH"
    assert a1["export"]["execution"]["executed_by_eva"] is True and a1["register"] == {"risk_before": "medium", "risk_after": "high"}
    assert a1["export"]["review"].startswith("NOT_APPLICABLE")
    d2 = a2["export"]
    assert d2["determination"]["customer_policy_outcome"] == "escalate"          # the determination stays escalate
    assert d2["review"]["outcome"] == "DECLINED" and d2["review"]["effects"]["authorizes_action"] is False
    assert d2["execution"]["executed_by_eva"] is False
    assert d2["evidence_chain"]["lineage"]["supersedes"] == V1


def test_v1_view_is_unchanged_by_v2_and_by_a_new_review(tmp_path):
    ev = tmp_path / "ev"
    fake = FakeEve()
    c1 = TestClient(webapp.create_app(pre_action=fake, runs_root=tmp_path / "r1", evidence_root=ev,
                                      intake_dirs=(INTAKES,), review_enabled=True,
                                      binding=lock_binding(B_V1, (INTAKES,)), expected_policy=P))
    par1 = c1.post("/api/turn", json={"utterance": "Raise Epsilon to high", "proposer": "scripted"}).json()["gate_decisions"][0]["eve_record_id"]
    before = c1.get(f"/api/audit/{par1}").json()
    c2 = demo_client(ev, fake, tmp_path=tmp_path)
    par2 = c2.post("/api/turn", json={"utterance": "Raise Epsilon to critical", "proposer": "scripted"}).json()["gate_decisions"][0]["eve_record_id"]
    assert c2.post("/api/review", json={"eve_record_id": par2, "outcome": "DECLINED", "reviewer": "R"}).status_code == 200
    after = c2.get(f"/api/audit/{par1}").json()
    assert after == before and after["export"]["execution"]["executed_by_eva"] is True


# ------------------------------------------------------------------ the only write, and what it can never do

@pytest.mark.parametrize("outcome", ["APPROVE", "ALLOW", "allow", "NEW_EVIDENCE", "OVERRIDE", ""])
def test_no_outcome_other_than_declined_or_handled_can_be_written(tmp_path, outcome):
    ev = tmp_path / "ev"
    c = demo_client(ev, tmp_path=tmp_path)
    par = c.post("/api/turn", json={"utterance": "Raise Epsilon to critical", "proposer": "scripted"}).json()["gate_decisions"][0]["eve_record_id"]
    r = c.post("/api/review", json={"eve_record_id": par, "outcome": outcome, "reviewer": "R"})
    assert r.status_code in (400, 409)
    assert not (ev / "reviews").exists() or not list((ev / "reviews").iterdir())


def test_review_rules_are_the_existing_d4_rules(tmp_path):
    ev = tmp_path / "ev"
    fake = FakeEve()
    c1 = TestClient(webapp.create_app(pre_action=fake, runs_root=tmp_path / "r1", evidence_root=ev,
                                      intake_dirs=(INTAKES,), review_enabled=True,
                                      binding=lock_binding(B_V1, (INTAKES,)), expected_policy=P))
    allow_par = c1.post("/api/turn", json={"utterance": "Raise Epsilon to high", "proposer": "scripted"}).json()["gate_decisions"][0]["eve_record_id"]
    c = demo_client(ev, fake, tmp_path=tmp_path)
    par = c.post("/api/turn", json={"utterance": "Raise Epsilon to critical", "proposer": "scripted"}).json()["gate_decisions"][0]["eve_record_id"]
    assert [i["eve_record_id"] for i in c.get("/api/review/queue").json()["items"]] == [par]
    calls_before = list(fake.calls)
    files_before = snapshot(ev)
    assert c.post("/api/review", json={"eve_record_id": allow_par, "outcome": "DECLINED", "reviewer": "R"}).json()["error_code"] == "NOT_A_REVIEW_ITEM"
    assert c.post("/api/review", json={"eve_record_id": "EVE-PAR-TEST-999999", "outcome": "DECLINED", "reviewer": "R"}).json()["error_code"] == "UNKNOWN_PAR"
    assert c.post("/api/review", json={"eve_record_id": par, "outcome": "DECLINED", "reviewer": "  "}).json()["error_code"] == "REVIEWER_REQUIRED"
    ok = c.post("/api/review", json={"eve_record_id": par, "outcome": "HANDLED_BY_HUMAN", "reviewer": "R", "note": "phoned supplier"})
    assert ok.status_code == 200 and ok.json()["effects"]["authorizes_action"] is False
    assert c.post("/api/review", json={"eve_record_id": par, "outcome": "DECLINED", "reviewer": "R"}).json()["error_code"] == "REVIEW_EXISTS"
    added = set(snapshot(ev)) - set(files_before)
    assert len(added) == 1 and next(iter(added)).startswith("reviews") and \
        {k: v for k, v in snapshot(ev).items() if k in files_before} == files_before
    for path in ("/api/history", "/api/review/queue", f"/api/audit/{par}", f"/api/audit/{allow_par}"):
        assert c.get(path).status_code == 200
    assert fake.calls == calls_before                                        # review and audit never call EVE
    assert c.get(f"/api/audit/{par}").json()["export"]["determination"]["customer_policy_outcome"] == "escalate"


def test_closed_evidence_is_never_appended_to(tmp_path):
    ev = copy_demo(tmp_path)
    before = snapshot(ev)
    c = demo_client(ev, review_enabled=False, tmp_path=tmp_path)
    assert c.get("/api/history").json()["review_enabled"] is False
    r = c.post("/api/review", json={"eve_record_id": "EVE-PAR-LOCAL-000025", "outcome": "DECLINED", "reviewer": "R"})
    assert r.status_code == 403 and r.json()["error_code"] == "REVIEW_DISABLED"
    assert snapshot(ev) == before


def test_the_page_offers_no_approve_action():
    html = (REPO / "eva" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"for\(const \[o,label\] of (\[\[.*?\]\])\)", html)
    assert m and set(re.findall(r'\["([A-Z_]+)",', m.group(1))) == set(act4.UI_OUTCOMES)
    assert "innerHTML" not in html


# ------------------------------------------------------------------ UI-1 absence is visible

def test_absence_and_declared_values_are_shown_as_such():
    kinds = {b["item"]: b["status"] for b in act4.BOUNDARIES}
    assert kinds["Reviewer identity"] == "NOT_ESTABLISHED"
    assert kinds["EVE installation identity"] == "DECLARED_BY_OPERATOR"
    h = act4.history(I4)                                                    # turn records written before D5
    assert h["items"] and all(isinstance(i["binding"], str) and i["binding"].startswith("NOT_ESTABLISHED") for i in h["items"])
    par = h["items"][0]["eve_record_id"]
    a = act4.audit_view(I4, (), par)
    assert a["verification"] == "VERIFIED"
    assert a["policy_comparison"].startswith("NOT_ESTABLISHED")
    assert a["export"]["policy"]["policy_content_sha256"].startswith("NOT_ESTABLISHED")
    assert a["export"]["evidence_chain"]["lineage"].startswith("NOT_ESTABLISHED")


# ------------------------------------------------------------------ UI-2 historical ordering

def test_order_and_times_come_from_the_records_not_from_the_file_system(tmp_path):
    ev = copy_demo(tmp_path)
    files = sorted(ev.glob("TURN_*.json"))
    for k, p in enumerate(files):                                            # newest file gets the oldest mtime
        os.utime(p, (10_000 + (len(files) - k) * 1000,) * 2)
    h = act4.history(ev, (INTAKES,))
    assert [i["eve_record_id"] for i in h["items"]] == ["EVE-PAR-LOCAL-000024", "EVE-PAR-LOCAL-000025"]
    for i in h["items"]:
        body = json.loads((ev / i["turn_record"]["file"]).read_text(encoding="utf-8"))
        assert i["turn_utc"] == body["turn_utc"]
    rv = json.loads(next((ev / "reviews").glob("REVIEW_*.json")).read_text(encoding="utf-8"))
    assert h["items"][1]["review"]["recorded_utc"] == rv["recorded_utc"]


# ------------------------------------------------------------------ UI-3 verification failure is visible

def test_a_changed_turn_record_fails_the_whole_view(tmp_path):
    ev = copy_demo(tmp_path)
    f = ev / "TURN_20261002T193916833249Z_1.json"
    body = json.loads(f.read_text(encoding="utf-8"))
    body["observed"]["risk_after"] = "low"
    f.write_text(json.dumps(body), encoding="utf-8")
    c = demo_client(ev, tmp_path=tmp_path)
    for path in ("/api/history", "/api/review/queue", "/api/audit/EVE-PAR-LOCAL-000025"):
        r = c.get(path)
        assert r.status_code == 409 and r.json()["verification"] == "FAILED"
        assert r.json()["error_code"] == "RECORD_TAMPERED" and r.json()["message"] == act4.VERIFICATION_FAILED


def test_a_changed_review_or_intake_record_fails_the_audit(tmp_path):
    ev = copy_demo(tmp_path)
    rf = next((ev / "reviews").glob("REVIEW_*.json"))
    rb = json.loads(rf.read_text(encoding="utf-8"))
    rb["outcome"] = "NEW_EVIDENCE"
    rf.write_text(json.dumps(rb), encoding="utf-8")
    with pytest.raises(act4.Act4Error) as e:
        act4.audit_view(ev, (INTAKES,), "EVE-PAR-LOCAL-000025")
    assert e.value.code == "RECORD_TAMPERED"
    ev2 = copy_demo(tmp_path / "b")
    intakes = tmp_path / "intakes"
    shutil.copytree(INTAKES, intakes)
    inf = next(intakes.glob("INTAKE_*_SAVE_EVA-CH-995bf*.json"))
    ib = json.loads(inf.read_text(encoding="utf-8"))
    ib["supersedes"] = None
    inf.write_text(json.dumps(ib), encoding="utf-8")
    with pytest.raises(act4.Act4Error) as e:
        act4.audit_view(ev2, (intakes,), "EVE-PAR-LOCAL-000025")
    assert e.value.code == "RECORD_TAMPERED"


def test_a_source_that_changes_after_the_export_is_built_is_never_shown_as_verified(tmp_path, monkeypatch):
    ev = copy_demo(tmp_path)
    real = act4._source_paths

    def changed(evidence_root, intake_dirs):
        paths = real(evidence_root, intake_dirs)
        alt = tmp_path / "alt.json"
        alt.write_bytes(paths["TURN_20261002T194116767481Z_1.json"].read_bytes() + b" ")
        paths["TURN_20261002T194116767481Z_1.json"] = alt
        return paths
    monkeypatch.setattr(act4, "_source_paths", changed)
    with pytest.raises(act4.Act4Error) as e:
        act4.audit_view(ev, (INTAKES,), "EVE-PAR-LOCAL-000025")
    assert e.value.code == "SOURCE_CHANGED"


def test_an_unreadable_record_is_a_failure_not_an_empty_history(tmp_path):
    ev = copy_demo(tmp_path)
    (ev / "TURN_20261002T194116767481Z_1.json").write_bytes(b"\xff\xfe not json")
    with pytest.raises(act4.Act4Error) as e:
        act4.history(ev, (INTAKES,))
    assert e.value.code == "RECORD_UNREADABLE"


# ------------------------------------------------------------------ a closed package is never a runtime directory

def test_starting_against_a_closed_evidence_package_stops_before_anything_runs(tmp_path, monkeypatch):
    ev = copy_demo(tmp_path)
    before = snapshot(ev)
    touched = []

    class NoEve:
        def __init__(self, *a, **k):
            touched.append("EveMcpClient")
    monkeypatch.setattr(webapp, "EveMcpClient", NoEve)
    monkeypatch.setattr(webapp, "create_app", lambda *a, **k: touched.append("create_app"))
    monkeypatch.setattr(webapp, "lock_binding", lambda *a, **k: touched.append("lock_binding"))
    with pytest.raises(SystemExit) as e:
        webapp.main(["--binding", str(B_V2), "--intakes", str(INTAKES), "--evidence-dir", str(ev)])
    assert e.value.code == 2
    assert touched == []                                                     # no binding lock, no app, no EVE client
    assert snapshot(ev) == before                                            # not one byte written
