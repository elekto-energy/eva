"""cli_bedrock never writes into a closed evidence package (a directory holding *_RUN_INDEX_*.json).

The sealed evidence/i3b package (commit 42ffa4e) is only READ here -- snapshotted before and after; it is
never written, renamed or copied into. Every run that is allowed to write happens in tmp_path. No test makes
a Bedrock or EVE call: the functions that would are replaced with recorders.
"""
import json
import shutil
from pathlib import Path

import pytest

from eva import cli_bedrock as cb

REPO = Path(__file__).resolve().parent.parent
SEALED = REPO / "evidence" / "i3b"


def snapshot(d: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()}


@pytest.fixture
def recorder(monkeypatch):
    """Every way cli_bedrock could reach the frozen check, Bedrock or EVE is replaced and recorded."""
    calls = []
    monkeypatch.setattr(cb, "verify_frozen_boundary", lambda: calls.append("verify_frozen_boundary") or {})
    monkeypatch.setattr(cb, "build_nova_model", lambda: calls.append("build_nova_model"))
    monkeypatch.setattr(cb, "EveMcpClient", lambda *a, **k: calls.append("EveMcpClient"))
    monkeypatch.setattr(cb, "run_proof", lambda: calls.append("run_proof") or
                        {"mode": "proof", "classification": "PASS", "text": "OK"})
    monkeypatch.setattr(cb, "run_attempt", lambda mode, case, ts, n: calls.append(f"run_attempt:{mode}") or
                        {"attempt": n, "classification": "PASS", "why": "stub"})
    return calls


@pytest.mark.skipif(not any(SEALED.glob("*_RUN_INDEX_*.json")), reason="sealed i3b package not present")
@pytest.mark.parametrize("argv", [["--proof"], ["--case", "A"], ["--case", "B"], ["--eve-down"]])
def test_the_sealed_i3b_package_is_refused_by_default_and_never_touched(recorder, argv, capsys):
    before = snapshot(SEALED)
    runs_before = sorted(p.name for p in (REPO / "runs").iterdir()) if (REPO / "runs").is_dir() else []
    rc = cb.main(argv)
    assert rc == 4 and "closed evidence package" in capsys.readouterr().out
    assert recorder == []                                    # no frozen check, no Nova, no EVE, no attempt
    assert snapshot(SEALED) == before                        # not one byte changed
    runs_after = sorted(p.name for p in (REPO / "runs").iterdir()) if (REPO / "runs").is_dir() else []
    assert runs_after == runs_before                         # no run directory was created either


def test_any_directory_holding_a_run_index_is_refused(tmp_path, recorder):
    closed = tmp_path / "closed"
    closed.mkdir()
    (closed / "ANY_RUN_INDEX_2026-01-01.json").write_text("{}", encoding="utf-8")
    (closed / "RUNB_x_proof.json").write_text("{}", encoding="utf-8")
    before = snapshot(closed)
    assert cb.main(["--proof", "--evidence-dir", str(closed)]) == 4
    assert recorder == [] and snapshot(closed) == before


def test_a_new_directory_receives_exactly_one_record(tmp_path, recorder):
    sealed_before = snapshot(SEALED) if SEALED.is_dir() else None
    out_dir = tmp_path / "i3b_next"
    assert cb.main(["--proof", "--evidence-dir", str(out_dir)]) == 0
    files = list(out_dir.iterdir())
    assert len(files) == 1 and files[0].name.startswith("RUNB_") and files[0].name.endswith("_proof.json")
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["classification"] == "PASS" and rec["record_kind"] == "eva_i3b_run"
    assert recorder == ["verify_frozen_boundary", "run_proof"]
    if sealed_before is not None:
        assert snapshot(SEALED) == sealed_before             # the sealed package stays untouched


def test_an_existing_open_directory_is_accepted(tmp_path, recorder):
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    (open_dir / "RUNB_earlier_proof.json").write_text("{}", encoding="utf-8")
    assert cb.main(["--eve-down", "--evidence-dir", str(open_dir)]) == 0
    assert len(list(open_dir.glob("RUNB_*_eve-down.json"))) == 1
    assert recorder == ["verify_frozen_boundary", "run_attempt:eve-down"]
