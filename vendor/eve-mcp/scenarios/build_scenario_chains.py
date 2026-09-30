"""build_scenario_chains.py -- declared-scenario chains for the eve-mcp acceptance.

WHAT THIS IS
    An OPERATOR-side instrument that materialises the two acceptance chains
    (CASE_A / CASE_B) into an EVE demo instance's EXTERNAL runtime store.
    It follows the precedent of agents/eve_grc_agent/.../build_runtime_demo_chain.py
    (2026-08-23): a chain saved with storage.save_chain() is served by the real
    pre-action route immediately; resolve()'s CHAIN_CONFIGS restriction applies
    only to /api/chain/resolve.

WHAT IT NEVER DOES
    - It never fills in a derived field by hand. overall_verdict, gaps,
      control_result_supported, human_review_required and action_gate are
      produced by EVE's OWN engine functions (adapters, verdict, governance,
      derive_action_gate) over the DECLARED scenario data, composed exactly as
      core/eve_chain/resolver.py composes them.
    - It never modifies the EVE checkout, never overwrites an existing chain,
      never writes into the checkout (require_external_store() is enforced
      BEFORE any store module is imported -- the Stage-1 invariant).
    - It never seals, anchors or evaluates policy: those are the real EVE
      routes' jobs in the acceptance run.

EQUIVALENCE GATE
    The composition is a MIRROR of resolve(). Before any scenario is built the
    mirror is proven faithful: composed over the canonical examples fixtures it
    must reproduce resolve("ai_agent_action").to_dict() and content_hash
    exactly. A drift in resolver.py therefore fails this instrument closed
    instead of silently producing a chain EVE itself would not have produced.

USAGE (venv_gpu python; read-only unless --save)
    python build_scenario_chains.py --eve-checkout D:\\EVE_DEMO\\eve-core-v1
        --expected-tree a698922c9fd740c4b114e572a626380abf1590a4
        --scenarios scenarios_v1.json --evidence-dir ..\\evidence [--save]
    EVE_RUNTIME_STORE_ROOT must be set to an EXTERNAL directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

INSTRUMENT_VERSION = "eve-mcp-scenario-builder-0.1.0"
AI_CHAIN_TYPE = "ai_agent_action"
# Mirror of resolver._GOV_FACT_FIELDS; asserted equal at runtime (fail closed on drift).
GOV_FACT_FIELDS = {
    "chain_authorisation_status", "chain_authorised_by", "chain_authorisation_scope",
    "chain_authorisation_expires_at", "chain_current_scope", "chain_owner",
    "chain_owner_confirmed", "chain_monitoring_owner", "chain_monitoring_status",
    "chain_review_cycle",
}


def now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def stop(code: int, msg: str) -> "NoReturn":
    sys.stderr.write(f"STOP [{code}] {msg}\n")
    sys.exit(code)


def git_tree(checkout: str) -> tuple[str, str, str]:
    """Measure HEAD and HEAD^{tree} of the checkout. Uses `git` from PATH; the
    executable path is recorded in the evidence (not H6 trusted-git)."""
    git = shutil.which("git")
    if not git:
        stop(3, "git executable not found on PATH; cannot verify checkout identity")
    def run(*args):
        return subprocess.run([git, "-C", checkout, *args], capture_output=True, text=True, timeout=60)
    head = run("rev-parse", "HEAD"); tree = run("rev-parse", "HEAD^{tree}")
    if head.returncode or tree.returncode:
        stop(3, f"git rev-parse failed in {checkout}: {head.stderr.strip()} {tree.stderr.strip()}")
    return git, head.stdout.strip(), tree.stdout.strip()


def compose(eve, steps_cfg, cfg_like: dict, raw: dict, governance: dict, chain_id: str, created_at: str):
    """Exact mirror of core/eve_chain/resolver.resolve() for chain_type ai_agent_action.

    steps_cfg is ALWAYS examples.CHAIN_CONFIGS["ai_agent_action"]["steps"] -- the canonical,
    unchanged step tuple of the AI chain. Scenarios declare data, never steps."""
    adapters = eve["build_adapters"](eve["AdapterMode"].STUB)
    context = {"raw": raw, "chain_type": AI_CHAIN_TYPE}
    signals, steps, source_systems, requirements = [], [], [], []
    for (step_id, label, adapter_key, check, required) in steps_cfg:
        sig = adapters[adapter_key].fetch(check, context)
        signals.append(sig.to_dict())
        if sig.source_system not in source_systems:
            source_systems.append(sig.source_system)
        if required:
            requirements.append(step_id)
        steps.append(eve["ChainStep"](
            id=step_id, label=label, source_system=sig.source_system, required=required,
            status=sig.status, signal=sig.signal_type, timestamp=sig.timestamp or None,
            evidence_ref=sig.evidence_ref or None, hash=sig.hash, gap=sig.gap))
    verdict = eve["compute_verdict"](steps)
    eve["assert_no_silent_upgrade"](verdict, steps)
    resolved_at = created_at                      # STUB mode: resolved_at == created_at
    gov_kwargs = {k: v for k, v in governance.items() if k in GOV_FACT_FIELDS}
    gov_result = eve["resolve_chain_governance"](eve["GovernanceFacts"](**gov_kwargs), resolved_at)
    overall = eve["combine_overall_verdict"](verdict.overall_verdict, gov_result.governance_supported)
    human_review = verdict.human_review_required or (not gov_result.governance_supported)
    combined_gaps = list(verdict.gaps) + list(gov_result.gaps)
    gate_value = eve["derive_action_gate"](overall)
    steps.append(eve["ChainStep"](
        id="action_gate", label="Action gate resolved", source_system="Action Gate", required=False,
        status=gate_value, signal="action_gate", timestamp=resolved_at, evidence_ref=None, gap=None,
        derived=True, excluded_from_verdict=True))
    eve["assert_governance_consistency"](overall, gov_result)
    chain = eve["EveChain"](
        chain_id=chain_id, chain_type=AI_CHAIN_TYPE, decision=cfg_like["decision"],
        subject=cfg_like["subject"], expected_control_result=cfg_like.get("expected_control_result", ""),
        source_systems=source_systems, evidence_signals=signals, steps=[s.to_dict() for s in steps],
        requirements=requirements, gaps=combined_gaps, overall_verdict=overall,
        control_result_supported=(overall == eve["Status"].SUPPORTED.value),
        human_review_required=human_review, freshness_check_enabled=False, action_gate=gate_value,
        seal_id=None, verify_status=eve["VerifyStatus"].UNSEALED.value,
        created_at=created_at, resolved_at=resolved_at)
    g = governance
    chain.chain_authorisation_required = g.get("chain_authorisation_required", False)
    chain.chain_authorisation_status = g.get("chain_authorisation_status", chain.chain_authorisation_status)
    chain.chain_authorised_by = g.get("chain_authorised_by")
    chain.chain_authorised_at = g.get("chain_authorised_at")
    chain.chain_authorisation_basis = g.get("chain_authorisation_basis")
    chain.chain_authorisation_scope = g.get("chain_authorisation_scope")
    chain.chain_owner = g.get("chain_owner")
    chain.chain_owner_confirmed = g.get("chain_owner_confirmed", False)
    chain.chain_monitoring_status = g.get("chain_monitoring_status", chain.chain_monitoring_status)
    chain.chain_monitoring_owner = g.get("chain_monitoring_owner")
    chain.chain_review_cycle = g.get("chain_review_cycle")
    chain.chain_authorisation_expires_at = g.get("chain_authorisation_expires_at")
    chain.chain_current_scope = g.get("chain_current_scope")
    chain.content_hash = chain.compute_content_hash()
    return chain


def load_eve(checkout: str) -> dict:
    sys.path.insert(0, checkout)
    from core.eve_chain.store_path import require_external_store, StorePathConfigError
    try:
        store_dir = require_external_store()          # BEFORE any store module import
    except StorePathConfigError as exc:
        stop(3, f"runtime store refused: {exc}")
    from core.eve_chain import storage, resolver
    from core.eve_chain.adapters import AdapterMode, build_adapters
    from core.eve_chain.examples import CHAIN_CONFIGS, FIXTURES
    from core.eve_chain.schema import ChainStep, EveChain, Status, VerifyStatus, derive_action_gate
    from core.eve_chain.verdict import assert_no_silent_upgrade, compute_verdict
    from core.eve_chain.governance import (GovernanceFacts, assert_governance_consistency,
                                           combine_overall_verdict, resolve_chain_governance)
    if getattr(resolver, "_GOV_FACT_FIELDS", None) != GOV_FACT_FIELDS:
        stop(4, "resolver._GOV_FACT_FIELDS differs from this instrument's mirror; refusing to compose")
    return dict(store_dir=str(store_dir), storage=storage, resolve=resolver.resolve,
                AdapterMode=AdapterMode, build_adapters=build_adapters, CHAIN_CONFIGS=CHAIN_CONFIGS,
                FIXTURES=FIXTURES, ChainStep=ChainStep, EveChain=EveChain, Status=Status,
                VerifyStatus=VerifyStatus, derive_action_gate=derive_action_gate,
                assert_no_silent_upgrade=assert_no_silent_upgrade, compute_verdict=compute_verdict,
                GovernanceFacts=GovernanceFacts, assert_governance_consistency=assert_governance_consistency,
                combine_overall_verdict=combine_overall_verdict, resolve_chain_governance=resolve_chain_governance)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eve-checkout", required=True)
    ap.add_argument("--expected-tree", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--save", action="store_true", help="write the chains into the external store (default: print only)")
    a = ap.parse_args(argv)

    checkout = os.path.abspath(a.eve_checkout)
    git, head, tree = git_tree(checkout)
    if tree != a.expected_tree.lower():
        stop(3, f"checkout tree {tree} != expected {a.expected_tree}; refusing to build against an unpinned EVE")
    scen_sha = sha256_file(a.scenarios)
    with open(a.scenarios, "rb") as fh:
        doc = json.loads(fh.read().decode("utf-8"))
    if doc.get("scenario_schema_version") != "eve-mcp-scenario-1.0" or doc.get("chain_type") != AI_CHAIN_TYPE:
        stop(2, "scenarios file: unsupported schema version or chain_type")

    eve = load_eve(checkout)
    store_root = os.path.abspath(eve["store_dir"])
    if os.path.commonpath([store_root, checkout]) == checkout:
        stop(3, "external store resolves inside the checkout")   # belt and braces; store_path already refuses

    # ---- equivalence gate: the mirror must reproduce resolve() exactly ----
    cfg = eve["CHAIN_CONFIGS"][AI_CHAIN_TYPE]
    mirrored = compose(eve, cfg["steps"], cfg, eve["FIXTURES"][AI_CHAIN_TYPE], cfg.get("governance", {}),
                       cfg["chain_id"], cfg["created_at"])
    reference = eve["resolve"](AI_CHAIN_TYPE)
    if mirrored.to_dict() != reference.to_dict() or mirrored.content_hash != reference.content_hash:
        stop(4, "equivalence gate FAILED: the composition mirror does not reproduce resolve(); "
                "resolver.py has drifted from this instrument -- nothing was built")
    equivalence = {"status": "PASS", "reference_chain_id": reference.chain_id,
                   "reference_content_hash": reference.content_hash}

    record = {
        "record_kind": "eve_mcp_scenario_build", "record_schema_version": "eve-mcp-scenario-build-1.0",
        "instrument": {"version": INSTRUMENT_VERSION, "path": os.path.abspath(__file__),
                       "sha256": sha256_file(os.path.abspath(__file__))},
        "recorded_utc": now_z(), "mode": "SAVE" if a.save else "PRINT_ONLY",
        "eve_checkout": {"path": checkout, "head": head, "tree": tree, "git_executable": git,
                         "trusted_git_claim": "NONE (PATH git; not the H6 protected verifier)"},
        "runtime_store_root": store_root,
        "scenarios_file": {"path": os.path.abspath(a.scenarios), "sha256": scen_sha},
        "steps_source": "examples.CHAIN_CONFIGS['ai_agent_action']['steps'] (canonical, unchanged)",
        "equivalence_gate": equivalence, "scenarios": [],
    }
    for sc in doc["scenarios"]:
        chain = compose(eve, cfg["steps"], sc, sc["raw"], sc["governance"], sc["chain_id"], sc["created_at"])
        measured = {"overall_verdict": chain.overall_verdict, "action_gate": chain.action_gate,
                    "gap_codes": sorted({g["code"] for g in chain.gaps}),
                    "human_review_required": chain.human_review_required,
                    "control_result_supported": chain.control_result_supported,
                    "content_hash": chain.content_hash}
        exp = sc["expected"]
        expected_ok = (measured["overall_verdict"] == exp["overall_verdict"]
                       and measured["action_gate"] == exp["action_gate"]
                       and measured["gap_codes"] == sorted(exp["gap_codes"]))
        entry = {"scenario_id": sc["scenario_id"], "chain_id": sc["chain_id"], "measured": measured,
                 "expected": exp, "expected_met": expected_ok, "declared_data_sha256": canonical_sha256(sc),
                 "persisted": False, "readback_content_hash_match": None}
        print(f"{sc['scenario_id']} {sc['chain_id']}: verdict={measured['overall_verdict']} "
              f"gate={measured['action_gate']} gaps={measured['gap_codes']} content_hash={chain.content_hash}"
              f" expected_met={expected_ok}")
        if not expected_ok:
            record["scenarios"].append(entry)
            stop(5, f"{sc['scenario_id']}: engine-derived result does not meet the declared expectation; "
                    f"adjust the DECLARED data, never the derived fields. measured={measured}")
        if a.save:
            if eve["storage"].get_chain(sc["chain_id"]) is not None:
                stop(6, f"{sc['chain_id']} already exists in the store; this instrument never overwrites")
            eve["storage"].save_chain(chain)
            back = eve["storage"].get_chain(sc["chain_id"])
            if back is None:
                stop(6, f"{sc['chain_id']} not readable back after save")
            entry["persisted"] = True
            entry["readback_content_hash_match"] = (back.compute_content_hash() == chain.content_hash)
            if not entry["readback_content_hash_match"]:
                stop(6, f"{sc['chain_id']}: recomputed content_hash after readback differs; do not use this chain")
        record["scenarios"].append(entry)

    os.makedirs(a.evidence_dir, exist_ok=True)
    out = os.path.join(a.evidence_dir, f"SCENARIO_BUILD_{record['recorded_utc'].replace(':', '')}.json")
    if os.path.exists(out):
        stop(7, f"evidence file already exists: {out}")
    record["record_sha256"] = canonical_sha256(record)
    with open(out, "x", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"evidence {out} record_sha256={record['record_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
