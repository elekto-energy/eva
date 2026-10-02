"""EVA chain intake -- engine and CLI (operator side).

  set EVE_RUNTIME_STORE_ROOT=<external EVE store>          (required; checked by EVE itself)
  python -m eva_intake.intake --declaration FILE --eve-checkout DIR --expected-tree TREE [--save]
                              [--supersedes CHAIN_ID] [--evidence-dir DIR]

Steps, in order, all fail-closed:
  1. the vendored EVE MCP v1 scenario builder is byte-verified, then imported unchanged
     (compose / load_eve / git_tree are its functions);
  2. the EVE checkout tree must equal --expected-tree;
  3. EVE refuses a store that is not external (require_external_store, inside load_eve);
  4. equivalence gate: compose() must reproduce resolve("ai_agent_action") exactly;
  5. the declaration is validated strictly (eva_intake.declaration);
  6. the chain is composed by EVE's engine with a content-addressed chain id;
  7. an existing chain with the same id is never overwritten: identical content -> EXISTS_IDENTICAL,
     different content -> STOP; only --save writes, and the write is read back and hash-checked;
  8. one self-hashed intake record is written (exclusive create).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from .declaration import (DeclarationError, canonical_sha256, chain_id_for, load_json_strict, validate)

REPO = Path(__file__).resolve().parent.parent
BUILDER_PATH = REPO / "vendor" / "eve-mcp" / "scenarios" / "build_scenario_chains.py"
BUILDER_SHA256 = "d11c248409609e7a29b82ad34db6a26b23989e1723025005796def8696ce8f4b"
INSTRUMENT_VERSION = "eva-chain-intake-0.1.0"
AI_CHAIN_TYPE = "ai_agent_action"


class IntakeError(RuntimeError):
    def __init__(self, exit_code: int, code: str, detail: str):
        self.exit_code, self.code, self.detail = exit_code, code, detail
        super().__init__(f"{code}: {detail}")


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def is_inside(child: str, parent: str, pathmod=os.path) -> bool:
    """True if child is parent or below it. Paths on different Windows drives are never inside each
    other (os.path.commonpath raises ValueError for them instead of answering)."""
    try:
        return pathmod.commonpath([child, parent]) == parent
    except ValueError:
        return False


def load_builder(path: Path = BUILDER_PATH, expected_sha256: str = BUILDER_SHA256):
    """Import the vendored builder only if it is byte-identical to the pinned EVE MCP v1 file."""
    if not path.is_file():
        raise IntakeError(3, "BUILDER_MISSING", str(path))
    got = _sha256_file(path)
    if got != expected_sha256:
        raise IntakeError(3, "BUILDER_CHANGED", f"{path} sha256 {got} != pinned {expected_sha256}")
    spec = importlib.util.spec_from_file_location("eva_vendored_scenario_builder", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_engine(builder, checkout: str) -> dict:
    """EVE's own modules via the builder's load_eve (which enforces the external store first)."""
    try:
        return builder.load_eve(checkout)
    except SystemExit as exc:                     # the builder's stop() exits; keep it fail-closed
        raise IntakeError(3, "EVE_LOAD_REFUSED", f"builder.load_eve stopped with code {exc.code}") from None
    except Exception as exc:                      # e.g. EVE's own StorePathConfigError raised at import
        raise IntakeError(3, "EVE_LOAD_REFUSED", f"{type(exc).__name__}: {exc}") from None


def equivalence_gate(builder, eve: dict) -> dict:
    cfg = eve["CHAIN_CONFIGS"][AI_CHAIN_TYPE]
    mirrored = builder.compose(eve, cfg["steps"], cfg, eve["FIXTURES"][AI_CHAIN_TYPE],
                               cfg.get("governance", {}), cfg["chain_id"], cfg["created_at"])
    reference = eve["resolve"](AI_CHAIN_TYPE)
    if mirrored.to_dict() != reference.to_dict() or mirrored.content_hash != reference.content_hash:
        raise IntakeError(4, "EQUIVALENCE_FAILED", "compose() does not reproduce resolve(); nothing was built")
    return {"status": "PASS", "reference_chain_id": reference.chain_id,
            "reference_content_hash": reference.content_hash}


def enum_values(eve_schema_module) -> tuple[frozenset, frozenset]:
    return (frozenset(e.value for e in eve_schema_module.ChainAuthorisation),
            frozenset(e.value for e in eve_schema_module.ChainMonitoring))


def compose_chain(builder, eve: dict, decl: dict):
    cfg = eve["CHAIN_CONFIGS"][AI_CHAIN_TYPE]
    cfg_like = {"decision": decl["decision"], "subject": decl["subject"],
                "expected_control_result": decl["expected_control_result"]}
    chain_id = chain_id_for(decl)
    try:
        chain = builder.compose(eve, cfg["steps"], cfg_like, decl["raw"], decl["governance"],
                                chain_id, decl["declared_at"])
    except SystemExit as exc:
        raise IntakeError(4, "COMPOSE_REFUSED", f"builder stopped with code {exc.code}") from None
    return chain


def place_chain(eve: dict, chain, *, save: bool) -> str:
    """Never overwrite. Returns WOULD_CREATE | CREATED | EXISTS_IDENTICAL; raises on a conflict."""
    storage = eve["storage"]
    existing = storage.get_chain(chain.chain_id)
    if existing is not None:
        if existing.content_hash == chain.content_hash and existing.to_dict() == chain.to_dict():
            return "EXISTS_IDENTICAL"
        raise IntakeError(5, "CHAIN_ID_CONFLICT",
                          f"{chain.chain_id} exists with different content; nothing was written")
    if not save:
        return "WOULD_CREATE"
    storage.save_chain(chain)
    back = storage.get_chain(chain.chain_id)
    if back is None or back.content_hash != chain.content_hash or back.to_dict() != chain.to_dict():
        raise IntakeError(5, "READBACK_MISMATCH", f"{chain.chain_id} did not read back identically")
    return "CREATED"


def prepare_intake(builder, eve: dict, decl_bytes: bytes, *, supersedes: str | None,
                   authorisation_statuses: frozenset, monitoring_statuses: frozenset):
    """Validate and compose; writes nothing. Returns (chain, result-without-placement)."""
    try:
        decl = validate(load_json_strict(decl_bytes.decode("utf-8")),
                        authorisation_statuses=authorisation_statuses, monitoring_statuses=monitoring_statuses)
    except UnicodeDecodeError as exc:
        raise IntakeError(2, "INVALID_ENCODING", str(exc)) from None
    except json.JSONDecodeError as exc:
        raise IntakeError(2, "INVALID_JSON", str(exc)) from None
    except DeclarationError as exc:
        raise IntakeError(2, exc.code, f"{exc.path}: {exc.detail}") from None
    if supersedes is not None and (not supersedes.startswith("EVA-CH-") or any(c.isspace() for c in supersedes)):
        raise IntakeError(2, "INVALID_SUPERSEDES", "--supersedes must be an EVA-CH-... chain id")

    chain = compose_chain(builder, eve, decl)
    if supersedes == chain.chain_id:
        raise IntakeError(2, "INVALID_SUPERSEDES", "a chain cannot supersede itself")
    return chain, {
        "declaration_sha256": hashlib.sha256(decl_bytes).hexdigest(),
        "declaration_canonical_sha256": canonical_sha256(decl),
        "declared_by": decl["declared_by"], "declared_at": decl["declared_at"],
        "action_class": decl["action_class"], "subject_ref": decl["subject_ref"],
        "chain": {"chain_id": chain.chain_id, "content_hash": chain.content_hash,
                  "overall_verdict": chain.overall_verdict, "action_gate": chain.action_gate,
                  "human_review_required": chain.human_review_required, "gaps": chain.gaps},
        "supersedes": supersedes,
        "proposed_chain_map_binding": {decl["action_class"]: {decl["subject_ref"]: chain.chain_id}},
        "evidence_truth": "DECLARED -- EVE composes and verifies the declared record; it does not establish "
                          "that the declared evidence is true",
    }


def run_intake(builder, eve: dict, decl_bytes: bytes, *, save: bool, supersedes: str | None,
               authorisation_statuses: frozenset, monitoring_statuses: frozenset) -> dict:
    chain, result = prepare_intake(builder, eve, decl_bytes, supersedes=supersedes,
                                   authorisation_statuses=authorisation_statuses,
                                   monitoring_statuses=monitoring_statuses)
    return {"placement": place_chain(eve, chain, save=save), **result}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--declaration", required=True)
    ap.add_argument("--eve-checkout", required=True)
    ap.add_argument("--expected-tree", required=True)
    ap.add_argument("--save", action="store_true", help="write the chain into the external store")
    ap.add_argument("--supersedes", default=None)
    ap.add_argument("--evidence-dir", default=str(REPO / "evidence" / "intake"))
    a = ap.parse_args(argv)
    try:
        builder = load_builder()
        checkout = os.path.abspath(a.eve_checkout)
        try:
            git, head, tree = builder.git_tree(checkout)
        except SystemExit as exc:
            raise IntakeError(3, "TREE_UNMEASURABLE", f"git_tree stopped with code {exc.code}") from None
        if tree != a.expected_tree.lower():
            raise IntakeError(3, "TREE_MISMATCH", f"checkout tree {tree} != expected {a.expected_tree}")
        eve = load_engine(builder, checkout)
        store_root = os.path.abspath(eve["store_dir"])
        if is_inside(store_root, checkout):
            raise IntakeError(3, "STORE_INSIDE_CHECKOUT", store_root)
        equivalence = equivalence_gate(builder, eve)
        from core.eve_chain import schema as eve_schema   # importable after load_eve put the checkout on sys.path
        auth, mon = enum_values(eve_schema)
        decl_path = Path(a.declaration)
        chain, result = prepare_intake(builder, eve, decl_path.read_bytes(), supersedes=a.supersedes,
                                       authorisation_statuses=auth, monitoring_statuses=mon)
    except IntakeError as exc:
        print(f"STOP [{exc.exit_code}] {exc.code}: {exc.detail}")      # nothing was written anywhere
        return exc.exit_code

    # Reserve the record (exclusive create) BEFORE anything is written to the EVE store, so a stored chain
    # can never be left without its intake record.
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    mode = "SAVE" if a.save else "PRINT_ONLY"
    ev = Path(a.evidence_dir)
    ev.mkdir(parents=True, exist_ok=True)
    out = ev / f"INTAKE_{ts}_{mode}_{chain.chain_id}.json"
    try:
        fh = open(out, "x", encoding="utf-8", newline="\n")
    except FileExistsError:
        print(f"STOP [6] RECORD_EXISTS: {out}; nothing was written to the store")
        return 6
    record = {
        "record_kind": "eva_chain_intake", "record_schema_version": "eva-chain-intake-1.0",
        "recorded_utc": ts, "mode": mode,
        "instrument": {"version": INSTRUMENT_VERSION,
                       "declaration_module_sha256": _sha256_file(Path(__file__).with_name("declaration.py")),
                       "intake_module_sha256": _sha256_file(Path(__file__)),
                       "builder_sha256": BUILDER_SHA256},
        "eve_checkout": {"path": checkout, "head": head, "tree": tree, "git_executable": git},
        "external_store": store_root,
        "equivalence_gate": equivalence,
        "declaration_file": str(decl_path.resolve()),
    }
    exit_code = 0
    with fh:
        try:
            record["placement"] = place_chain(eve, chain, save=a.save)
            record.update(result)
        except IntakeError as exc:
            exit_code = exc.exit_code
            record.update(result)
            record["placement"] = "STOP"
            record["stop"] = {"exit_code": exc.exit_code, "code": exc.code, "detail": exc.detail}
        record["record_sha256"] = canonical_sha256(record)
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    c = result["chain"]
    if exit_code:
        print(f"STOP [{exit_code}] {record['stop']['code']}: {record['stop']['detail']}")
    else:
        print(f"{record['placement']} {c['chain_id']} verdict={c['overall_verdict']} gate={c['action_gate']}")
    print(f"intake record {out} record_sha256={record['record_sha256']}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
