"""S1-lite increment 2: DW declarations built deterministically from confirmed records (D-beta), checked by
eva_intake's own validator and -- with EVA_EVE_CHECKOUT set -- composed by EVE's own frozen engine (no store write).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eva_delegation import build_declaration as cli
from eva_delegation.declarations import (build_declaration, declaration_bytes, evidence_records, mandate_scope,
                                         records_bytes, requested_scope)
from eva_delegation.mandate import (MandateError, confirm_authorization, confirm_mandate, propose_authorization,
                                    propose_mandate)
from eva_delegation.tools import load_offers
from eva_intake import declaration as D
from eva_intake import intake as I
from eva_review.audit import AuditError, subject_of

OFFER_ID = "DW-OFFER-001"
OFFER = load_offers()[OFFER_ID]


def mandate(limit=200):
    p = propose_mandate(service="dishwasher_repair", limit_usd=limit, window="this week")
    return confirm_mandate(p, confirmed_by="Joakim Eklund", confirmation_utterance="Yes.", read_back_shown=p["read_back"])


def authorization():
    p = propose_authorization(offer=OFFER, offer_id=OFFER_ID, approved_usd=275)
    return confirm_authorization(p, confirmed_by="Joakim Eklund", confirmation_utterance="$275 is fine.",
                                 read_back_shown=p["read_back"])


def valid(decl):
    return D.validate(decl, authorisation_statuses=cli.AUTH, monitoring_statuses=cli.MON)


# ------------------------------------------------------------------ declarations from records (no EVE needed)
def test_v1_mandate_only_declares_a_scope_mismatch():
    m = mandate()
    d = valid(build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER))
    a = d["raw"]["approval"]
    assert d["action_class"] == "book_service_visit" and d["subject_ref"] == OFFER_ID
    assert a["approved"] is True and a["approver"] == "Joakim Eklund"
    assert a["requested_scope"] == "book_service_visit DW-OFFER-001 dishwasher_repair USD 275"
    assert a["approved_scope"] == "book_service_visit dishwasher_repair up to USD 200 this week"


def test_v2_with_exact_authorization_declares_the_requested_scope():
    m, auth = mandate(), authorization()
    a = valid(build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=auth))["raw"]["approval"]
    assert a["approved_scope"] == a["requested_scope"]


def test_same_records_give_byte_identical_declarations():
    m, auth = mandate(), authorization()
    one = declaration_bytes(build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=auth))
    two = declaration_bytes(build_declaration(mandate=copy.deepcopy(m), offer_id=OFFER_ID, offer=dict(OFFER),
                                              authorization=copy.deepcopy(auth)))
    assert one == two


def test_documents_hash_is_the_hash_of_the_records_it_was_built_from():
    m, auth = mandate(), authorization()
    d = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=auth)
    rb = records_bytes(evidence_records(m, OFFER_ID, OFFER, auth))
    assert d["raw"]["documents"]["sha256"] == hashlib.sha256(rb).hexdigest()


def test_v1_and_v2_are_different_chains():
    m = mandate()
    v1 = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER)
    v2 = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=authorization())
    assert I.chain_id_for(v1) != I.chain_id_for(v2)


def test_timestamps_come_from_the_records_not_the_clock():
    m = mandate()
    d = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER)
    assert d["declared_at"] == d["raw"]["approval"]["timestamp"] == d["governance"]["chain_authorised_at"]
    assert m["confirmed_at"].startswith(d["declared_at"][:19].replace("Z", ""))


def _reseal_at(rec: dict, iso: str) -> dict:
    """The same confirmed record, confirmed at a fixed past time (re-sealed), so the clock cannot coincide."""
    from eva_delegation.mandate import seal
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    body["confirmed_at"] = iso
    return seal(body)


def test_declared_times_are_exactly_the_record_times_not_the_clock():
    m = _reseal_at(mandate(), "2026-10-01T09:30:15.123456+00:00")
    a = _reseal_at(authorization(), "2026-10-02T14:05:59.999999+00:00")
    v1 = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER)
    v2 = build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=a)
    assert v1["declared_at"] == v1["raw"]["approval"]["timestamp"] == "2026-10-01T09:30:15Z"
    assert v2["declared_at"] == "2026-10-02T14:05:59Z"                    # the later of the two records
    assert v2["governance"]["chain_authorised_at"] == "2026-10-01T09:30:15Z"
    assert {s["timestamp"] for s in v2["raw"].values()} == {"2026-10-02T14:05:59Z"}


def test_a_proposal_or_a_tampered_record_gives_no_declaration():
    p = propose_mandate(service="dishwasher_repair", limit_usd=200, window="this week")
    with pytest.raises(MandateError):
        build_declaration(mandate=p, offer_id=OFFER_ID, offer=OFFER)
    m = mandate()
    m["limit_usd"] = 300
    with pytest.raises(MandateError):
        build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER)
    auth = authorization()
    auth["approved_usd"] = 200
    with pytest.raises(MandateError):
        build_declaration(mandate=mandate(), offer_id=OFFER_ID, offer=OFFER, authorization=auth)


def test_scope_strings():
    assert requested_scope(OFFER_ID, OFFER) == "book_service_visit DW-OFFER-001 dishwasher_repair USD 275"
    assert mandate_scope(mandate(150)) == "book_service_visit dishwasher_repair up to USD 150 this week"


# ------------------------------------------------------------------ intake action classes + audit subject key
def test_intake_accepts_both_action_classes_and_still_refuses_others():
    assert D.ACTION_CLASSES == ("set_supplier_risk_status", "book_service_visit")
    d = build_declaration(mandate=mandate(), offer_id=OFFER_ID, offer=OFFER)
    d["action_class"] = "unlock_front_door"
    with pytest.raises(D.DeclarationError) as e:
        valid(d)
    assert e.value.code == "UNSUPPORTED_ACTION_CLASS"


def test_audit_subject_key_per_action_class():
    assert subject_of({"tool_name": "set_supplier_risk_status", "args": {"supplier_id": "SUP-EPSILON-001"}}) \
        == "SUP-EPSILON-001"
    assert subject_of({"tool_name": "book_service_visit", "args": {"offer_id": OFFER_ID, "price_usd": 275}}) == OFFER_ID
    with pytest.raises(AuditError) as e:
        subject_of({"tool_name": "pay_invoice", "args": {"supplier_id": "X"}})
    assert e.value.code == "UNKNOWN_ACTION_CLASS"


# ------------------------------------------------------------------ the operator CLI
def _write(tmp: Path, name: str, obj) -> str:
    p = tmp / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_cli_writes_records_and_declaration_exclusively(tmp_path, capsys):
    mf = _write(tmp_path, "m.json", mandate())
    af = _write(tmp_path, "a.json", authorization())
    out = tmp_path / "out"
    assert cli.main(["--mandate", mf, "--offer-id", OFFER_ID, "--out-dir", str(out)]) == 0
    assert cli.main(["--mandate", mf, "--authorization", af, "--offer-id", OFFER_ID, "--out-dir", str(out)]) == 0
    files = sorted(p.name for p in out.iterdir())
    assert sum(n.startswith("DW_DECLARATION_MANDATE_ONLY_") for n in files) == 1
    assert sum(n.startswith("DW_DECLARATION_WITH_AUTHORIZATION_") for n in files) == 1
    assert sum(n.startswith("DW_EVIDENCE_RECORDS_") for n in files) == 2
    for p in out.glob("DW_DECLARATION_*.json"):
        d = valid(json.loads(p.read_text(encoding="utf-8")))
        rec = out / d["raw"]["documents"]["file"]
        assert hashlib.sha256(rec.read_bytes()).hexdigest() == d["raw"]["documents"]["sha256"]
    assert cli.main(["--mandate", mf, "--offer-id", OFFER_ID, "--out-dir", str(out)]) == 5      # never overwrites
    assert "QUOTE_EXCEEDS_MANDATE_LIMIT" in capsys.readouterr().out


def test_cli_refuses_a_closed_package_and_bad_input(tmp_path):
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "X_RUN_INDEX_2026-01-01.json").write_text("{}", encoding="utf-8")
    mf = _write(tmp_path, "m.json", mandate())
    assert cli.main(["--mandate", mf, "--offer-id", OFFER_ID, "--out-dir", str(closed)]) == 4
    assert sorted(p.name for p in closed.iterdir()) == ["X_RUN_INDEX_2026-01-01.json"]
    pf = _write(tmp_path, "p.json", propose_mandate(service="dishwasher_repair", limit_usd=200, window="this week"))
    assert cli.main(["--mandate", pf, "--offer-id", OFFER_ID, "--out-dir", str(tmp_path / "o2")]) == 2
    assert cli.main(["--mandate", mf, "--offer-id", "DW-OFFER-404", "--out-dir", str(tmp_path / "o3")]) == 2


# ------------------------------------------------------------------ EVE's own frozen engine (no store write)
# EVE core reads EVE_RUNTIME_STORE_ROOT once, at import. Composing in THIS interpreter would fix the store root for
# every later test (tests/test_intake.py relies on setting its own). So EVE runs in a separate interpreter with its
# own temporary store; nothing is shared with the rest of the suite.
CHECKOUT = os.environ.get("EVA_EVE_CHECKOUT")
needs_eve = pytest.mark.skipif(not CHECKOUT, reason="set EVA_EVE_CHECKOUT to an eve-core-v1 checkout")
REPO = Path(__file__).resolve().parent.parent

_COMPOSE = r"""
import json, os, sys, tempfile
os.environ["EVE_RUNTIME_STORE_ROOT"] = tempfile.mkdtemp(prefix="eva_dw_store_")
sys.path.insert(0, sys.argv[1])
from eva_intake import intake as I
builder = I.load_builder()
eve = I.load_engine(builder, os.path.abspath(sys.argv[2]))
from core.eve_chain import schema
auth, mon = I.enum_values(schema)
out = {"enums": [sorted(auth), sorted(mon)], "chains": []}
for path in sys.argv[3:]:
    chain, result = I.prepare_intake(builder, eve, open(path, "rb").read(), supersedes=None,
                                     authorisation_statuses=auth, monitoring_statuses=mon)
    out["chains"].append({"chain_id": chain.chain_id, "verdict": chain.overall_verdict, "gate": chain.action_gate,
                          "human_review": chain.human_review_required, "gaps": chain.gaps,
                          "binding": result["proposed_chain_map_binding"]})
print(json.dumps(out))
"""


def eve_compose(tmp_path, *decls):
    paths = []
    for i, d in enumerate(decls):
        p = tmp_path / f"decl_{i}.json"
        p.write_bytes(declaration_bytes(d))
        paths.append(str(p))
    r = subprocess.run([sys.executable, "-c", _COMPOSE, str(REPO), CHECKOUT, *paths],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_eve
def test_eve_v1_escalates_for_scope_mismatch_and_v2_is_supported(tmp_path):
    m = mandate()
    out = eve_compose(tmp_path, build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER),
                      build_declaration(mandate=m, offer_id=OFFER_ID, offer=OFFER, authorization=authorization()))
    v1, v2 = out["chains"]
    assert v1["gate"] == "HUMAN_REVIEW_REQUIRED" and v1["human_review"] is True
    assert [g["code"] for g in v1["gaps"]] == ["APPROVAL_SCOPE_MISMATCH"]
    assert v1["gaps"][0]["step_id"] == "human_approval" and "up to USD 200" in v1["gaps"][0]["text"]
    assert v1["binding"] == {"book_service_visit": {OFFER_ID: v1["chain_id"]}}
    assert v2["gate"] == "ACTION_CHAIN_SUPPORTED" and v2["human_review"] is False and v2["gaps"] == []
    assert v1["chain_id"] != v2["chain_id"]


@needs_eve
def test_eve_within_a_higher_mandate_is_supported_without_authorization(tmp_path):
    out = eve_compose(tmp_path, build_declaration(mandate=mandate(300), offer_id=OFFER_ID, offer=OFFER))
    assert out["chains"][0]["gate"] == "ACTION_CHAIN_SUPPORTED"


@needs_eve
def test_cli_enum_sets_equal_the_frozen_eve_schema(tmp_path):
    out = eve_compose(tmp_path)
    assert out["enums"] == [sorted(cli.AUTH), sorted(cli.MON)]
