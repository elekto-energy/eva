"""Step 1 -- chain intake. Unit tests need nothing external; integration tests need an EVE core checkout
(set EVA_EVE_CHECKOUT) and run against EVE's own engine with a temporary external store."""
import copy
import json
import os
import tempfile
from pathlib import Path

import pytest

from eva_intake import declaration as D
from eva_intake import intake as I

REF = Path(__file__).resolve().parent.parent / "eva_intake" / "reference"
V1 = json.loads((REF / "epsilon_v1_complete.json").read_text(encoding="utf-8"))
V2 = json.loads((REF / "epsilon_v2_approval_withdrawn.json").read_text(encoding="utf-8"))
AUTH = frozenset({"not_evaluated", "authorised", "not_authorised", "scope_mismatch", "expired"})
MON = frozenset({"not_evaluated", "monitored", "unmonitored"})


def ok(d):
    return D.validate(d, authorisation_statuses=AUTH, monitoring_statuses=MON)


def refused(d, code):
    with pytest.raises(D.DeclarationError) as e:
        ok(d)
    assert e.value.code == code, str(e.value)
    return e.value


# ------------------------------------------------------------------ validation (no EVE needed)

def test_reference_declarations_are_valid():
    assert ok(copy.deepcopy(V1)) and ok(copy.deepcopy(V2))


def test_unknown_field_is_refused_at_every_level():
    for path in (["extra"], ["governance", "extra"], ["raw", "extra"], ["raw", "approval", "extra"]):
        d = copy.deepcopy(V1)
        node = d
        for p in path[:-1]:
            node = node[p]
        node[path[-1]] = "x"
        refused(d, "UNKNOWN_FIELD")


@pytest.mark.parametrize("step,field", [("identity", "authority_in_scope"), ("tool_permission", "overscoped"),
                                        ("approval", "approved_scope"), ("approval", "requested_scope")])
def test_fields_the_core_would_default_must_be_declared(step, field):
    d = copy.deepcopy(V1)
    del d["raw"][step][field]
    e = refused(d, "MISSING_FIELD")
    assert e.path == f"$.raw.{step}.{field}"


def test_missing_governance_or_step_is_refused():
    d = copy.deepcopy(V1); del d["governance"]["chain_owner_confirmed"]; refused(d, "MISSING_FIELD")
    d = copy.deepcopy(V1); del d["raw"]["documents"]; refused(d, "MISSING_FIELD")


def test_types_are_exact_and_nothing_is_coerced():
    d = copy.deepcopy(V1); d["raw"]["approval"]["approved"] = "true"; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["raw"]["approval"]["approved_scope"] = None; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["raw"]["identity"]["authority_in_scope"] = 1; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["raw"]["documents"]["sha256"] = "ABC"; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["declared_at"] = "2026-02-30T00:00:00Z"; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["governance"]["chain_authorisation_status"] = "approved"; refused(d, "INVALID_TYPE")
    d = copy.deepcopy(V1); d["subject_ref"] = "SUP EPSILON"; refused(d, "INVALID_TYPE")


def test_schema_and_action_class_are_pinned():
    d = copy.deepcopy(V1); d["schema"] = "eva-evidence-declaration-2.0"; refused(d, "UNSUPPORTED_SCHEMA")
    d = copy.deepcopy(V1); d["action_class"] = "set_supplier_bank_account"; refused(d, "UNSUPPORTED_ACTION_CLASS")


def test_overscoped_that_contradicts_the_declared_scopes_fails_hard():
    d = copy.deepcopy(V1)
    d["raw"]["tool_permission"]["granted_scope"] = "update:*"            # broader than required, yet overscoped=false
    e = refused(d, "INCONSISTENT_OVERSCOPED")
    assert e.path == "$.raw.tool_permission.overscoped"
    d = copy.deepcopy(V1)
    d["raw"]["tool_permission"]["overscoped"] = True                      # equal scopes, yet overscoped=true
    refused(d, "INCONSISTENT_OVERSCOPED")


def test_duplicate_keys_are_refused():
    with pytest.raises(D.DeclarationError) as e:
        D.load_json_strict('{"schema": "a", "schema": "b"}')
    assert e.value.code == "DUPLICATE_KEY"


def test_chain_id_is_content_addressed_and_acceptable_to_eve_mcp():
    a, b = D.chain_id_for(copy.deepcopy(V1)), D.chain_id_for(copy.deepcopy(V1))
    assert a == b and a.startswith("EVA-CH-") and len(a) == 31
    assert D.chain_id_for(V2) != a
    d = copy.deepcopy(V1); d["raw"]["documents"]["timestamp"] = "2026-10-01T10:00:51Z"
    assert D.chain_id_for(d) != a                                          # any change -> new identity
    assert a == a.strip() and not any(c.isspace() for c in a) and len(a) <= 200   # EVE MCP v1 input rules


def test_builder_must_be_byte_identical(tmp_path):
    p = tmp_path / "build_scenario_chains.py"
    p.write_bytes(I.BUILDER_PATH.read_bytes() + b"\n# changed\n")
    with pytest.raises(I.IntakeError) as e:
        I.load_builder(p)
    assert e.value.code == "BUILDER_CHANGED"


# ------------------------------------------------------------------ integration with EVE's own engine

CHECKOUT = os.environ.get("EVA_EVE_CHECKOUT")
needs_eve = pytest.mark.skipif(not CHECKOUT, reason="set EVA_EVE_CHECKOUT to an eve-core-v1 checkout")


@pytest.fixture(scope="session")
def engine():
    store = tempfile.mkdtemp(prefix="eva_intake_store_")
    os.environ["EVE_RUNTIME_STORE_ROOT"] = store             # before any EVE store module is imported
    builder = I.load_builder()
    eve = I.load_engine(builder, os.path.abspath(CHECKOUT))
    from core.eve_chain import schema
    auth, mon = I.enum_values(schema)
    return builder, eve, auth, mon, Path(store) / "chains.json"


def intake(engine, decl, save=True, supersedes=None):
    builder, eve, auth, mon, _ = engine
    return I.run_intake(builder, eve, json.dumps(decl).encode("utf-8"), save=save, supersedes=supersedes,
                        authorisation_statuses=auth, monitoring_statuses=mon)


def variant(subject_ref):
    d = copy.deepcopy(V1)
    d["subject_ref"] = subject_ref
    return d


@needs_eve
def test_equivalence_gate_passes_against_resolve(engine):
    builder, eve, *_ = engine
    assert I.equivalence_gate(builder, eve)["status"] == "PASS"


@needs_eve
def test_enums_match_the_frozen_core(engine):
    _, _, auth, mon, _ = engine
    assert auth == AUTH and mon == MON


@needs_eve
def test_evidence_change_creates_a_new_version_and_never_rewrites_the_old_one(engine):
    _, eve, *_ = engine
    r1 = intake(engine, V1)
    assert r1["placement"] == "CREATED"
    assert (r1["chain"]["overall_verdict"], r1["chain"]["action_gate"]) == ("SUPPORTED", "ACTION_CHAIN_SUPPORTED")
    v1_before = eve["storage"].get_chain(r1["chain"]["chain_id"]).to_dict()

    r2 = intake(engine, V2, supersedes=r1["chain"]["chain_id"])
    assert r2["placement"] == "CREATED" and r2["chain"]["chain_id"] != r1["chain"]["chain_id"]
    assert (r2["chain"]["overall_verdict"], r2["chain"]["action_gate"]) == ("PARTIAL", "HUMAN_REVIEW_REQUIRED")
    assert r2["chain"]["human_review_required"] is True and r2["supersedes"] == r1["chain"]["chain_id"]

    v1_after = eve["storage"].get_chain(r1["chain"]["chain_id"]).to_dict()
    assert v1_after == v1_before                                   # the old evidence version is exactly preserved
    assert v1_after["action_gate"] == "ACTION_CHAIN_SUPPORTED"     # and still yields the same determination


@needs_eve
def test_same_declaration_again_is_identical_and_writes_nothing(engine):
    *_, store_file = engine
    d = variant("SUP-IDEM-001")
    assert intake(engine, d)["placement"] == "CREATED"
    before = store_file.read_bytes()
    assert intake(engine, d)["placement"] == "EXISTS_IDENTICAL"
    assert store_file.read_bytes() == before


@needs_eve
def test_print_only_never_writes(engine):
    *_, store_file = engine
    intake(engine, variant("SUP-SEED-001"))                     # make sure the store file exists
    before = store_file.read_bytes()
    r = intake(engine, variant("SUP-PRINT-001"), save=False)
    assert r["placement"] == "WOULD_CREATE" and store_file.read_bytes() == before


@needs_eve
def test_a_different_chain_under_the_same_id_is_a_conflict_and_nothing_is_written(engine):
    _, eve, *_ , store_file = engine
    d = variant("SUP-TAMPER-001")
    cid = intake(engine, d)["chain"]["chain_id"]
    tampered = eve["storage"].get_chain(cid)
    tampered.subject = "tampered"
    tampered.content_hash = tampered.compute_content_hash()
    eve["storage"].save_chain(tampered)                        # simulate a store altered outside the intake
    before = store_file.read_bytes()
    with pytest.raises(I.IntakeError) as e:
        intake(engine, d)
    assert e.value.code == "CHAIN_ID_CONFLICT" and store_file.read_bytes() == before


@needs_eve
def test_invalid_declaration_writes_nothing(engine):
    *_, store_file = engine
    intake(engine, variant("SUP-SEED-002"))
    before = store_file.read_bytes()
    d = variant("SUP-BAD-001"); del d["raw"]["identity"]["authority_in_scope"]
    with pytest.raises(I.IntakeError) as e:
        intake(engine, d)
    assert e.value.exit_code == 2 and e.value.code == "MISSING_FIELD" and store_file.read_bytes() == before


def test_cli_refuses_an_unpinned_eve_tree(monkeypatch, tmp_path, capsys):
    real = I.load_builder()

    class FakeBuilder:
        def __getattr__(self, name):
            return getattr(real, name)

        @staticmethod
        def git_tree(checkout):
            return ("git", "0" * 40, "1" * 40)

    monkeypatch.setattr(I, "load_builder", lambda: FakeBuilder())
    code = I.main(["--declaration", str(REF / "epsilon_v1_complete.json"), "--eve-checkout", str(tmp_path),
                   "--expected-tree", "a" * 40, "--evidence-dir", str(tmp_path / "ev")])
    assert code == 3 and "TREE_MISMATCH" in capsys.readouterr().out
    assert not (tmp_path / "ev").exists()


def test_eve_refusal_at_import_becomes_a_clean_stop():
    class Refusing:
        @staticmethod
        def load_eve(checkout):
            raise RuntimeError("EVE_RUNTIME_STORE_ROOT resolves inside the product repository")
    with pytest.raises(I.IntakeError) as e:
        I.load_engine(Refusing(), "/nowhere")
    assert e.value.exit_code == 3 and e.value.code == "EVE_LOAD_REFUSED"


def _cli_with_pinned_tree(monkeypatch):
    real = I.load_builder()

    class PinnedTree:
        def __getattr__(self, name):
            return getattr(real, name)

        @staticmethod
        def git_tree(checkout):
            return ("git", "0" * 40, "f" * 40)

    monkeypatch.setattr(I, "load_builder", lambda: PinnedTree())
    return ["--eve-checkout", os.path.abspath(CHECKOUT or "."), "--expected-tree", "f" * 40]


def _records(ev):
    out = []
    for p in sorted(ev.glob("INTAKE_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        body = {k: v for k, v in d.items() if k != "record_sha256"}
        assert D.canonical_sha256(body) == d["record_sha256"]
        out.append(d)
    return out


@needs_eve
def test_cli_every_run_gets_its_own_record_and_a_saved_chain_always_has_one(engine, monkeypatch, tmp_path):
    common = _cli_with_pinned_tree(monkeypatch)
    d = variant("SUP-CLI-001")
    decl = tmp_path / "decl.json"
    decl.write_text(json.dumps(d), encoding="utf-8")
    ev = tmp_path / "ev"
    args = ["--declaration", str(decl), *common, "--evidence-dir", str(ev)]
    assert I.main(args) == 0
    assert I.main([*args, "--save"]) == 0
    assert I.main([*args, "--save"]) == 0
    recs = _records(ev)
    assert [r["placement"] for r in sorted(recs, key=lambda r: r["recorded_utc"])] == \
        ["WOULD_CREATE", "CREATED", "EXISTS_IDENTICAL"]
    assert len({r["chain"]["chain_id"] for r in recs}) == 1


@needs_eve
def test_cli_conflict_writes_a_stop_record_and_leaves_the_store_untouched(engine, monkeypatch, tmp_path):
    _, eve, *_, store_file = engine
    common = _cli_with_pinned_tree(monkeypatch)
    d = variant("SUP-CLI-CONFLICT-001")
    cid = intake(engine, d)["chain"]["chain_id"]
    tampered = eve["storage"].get_chain(cid)
    tampered.subject = "tampered"
    tampered.content_hash = tampered.compute_content_hash()
    eve["storage"].save_chain(tampered)
    before = store_file.read_bytes()
    decl = tmp_path / "decl.json"
    decl.write_text(json.dumps(d), encoding="utf-8")
    ev = tmp_path / "ev"
    assert I.main(["--declaration", str(decl), *common, "--evidence-dir", str(ev), "--save"]) == 5
    (rec,) = _records(ev)
    assert rec["placement"] == "STOP" and rec["stop"]["code"] == "CHAIN_ID_CONFLICT"
    assert store_file.read_bytes() == before


@needs_eve
def test_cli_invalid_declaration_stops_before_any_record_or_write(engine, monkeypatch, tmp_path):
    *_, store_file = engine
    common = _cli_with_pinned_tree(monkeypatch)
    intake(engine, variant("SUP-SEED-003"))
    before = store_file.read_bytes()
    d = variant("SUP-CLI-BAD-001"); d["raw"]["tool_permission"]["granted_scope"] = "update:*"
    decl = tmp_path / "decl.json"
    decl.write_text(json.dumps(d), encoding="utf-8")
    ev = tmp_path / "ev"
    assert I.main(["--declaration", str(decl), *common, "--evidence-dir", str(ev), "--save"]) == 2
    assert not ev.exists() and store_file.read_bytes() == before


def test_store_on_another_windows_drive_is_never_inside_the_checkout():
    import ntpath
    assert I.is_inside(r"C:\Users\x\AppData\Local\Temp\store", r"D:\EVE11\staging\core", ntpath) is False
    assert I.is_inside(r"D:\EVE11\staging\core\inside", r"D:\EVE11\staging\core", ntpath) is True
    assert I.is_inside(r"D:\EVE11\store", r"D:\EVE11\staging\core", ntpath) is False
