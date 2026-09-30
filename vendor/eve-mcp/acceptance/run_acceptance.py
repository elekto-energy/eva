"""run_acceptance.py -- Phase 1 acceptance against the REAL pinned EVE.

Nothing in this harness is mocked. It STOPs (non-zero exit, no evidence
written as PASS) on the first condition it cannot establish. The evidence
record it writes carries identities and hashes only -- never the read token.

PRECONDITIONS (operator)
    1. EVE clone at tag eve-core-v1 with HEAD^{tree} == expected tree
    2. EVE started from that clone with an EXTERNAL EVE_RUNTIME_STORE_ROOT,
       bound to 127.0.0.1, PRE_ACTION_READ_TOKEN set in ITS environment
    3. scenario chains built with build_scenario_chains.py --save
    4. eve-mcp server started (python -m eve_mcp.server) against that EVE
    5. PRE_ACTION_READ_TOKEN exported in THIS shell for operator verification

USAGE (venv of eve-mcp, or venv_gpu)
    python run_acceptance.py --eve-checkout D:\\EVE_DEMO\\eve-core-v1
        --expected-tree a698922c9fd740c4b114e572a626380abf1590a4
        --eve-base-url http://127.0.0.1:8002 --mcp-url http://127.0.0.1:8765/mcp
        --registry ..\\policies\\policy_registry_v1.json --policy-ref eve-mcp-demo-policy-v1
        --scenarios ..\\scenarios\\scenarios_v1.json --evidence-dir ..\\evidence
        [--eve-suite-python D:\\EVE11\\venv_gpu\\Scripts\\python.exe]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from eve_mcp import core  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

HARNESS_VERSION = "eve-mcp-acceptance-0.1.0"
EXPECTED = {
    "CASE_A": {"verified_chain_outcome": "ACTION_CHAIN_SUPPORTED", "customer_policy_outcome": "allow"},
    "CASE_B": {"verified_chain_outcome": "HUMAN_REVIEW_REQUIRED", "customer_policy_outcome": "escalate"},
}


def now_z():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def stop(code, msg):
    sys.stderr.write(f"STOP [{code}] {msg}\n")
    sys.exit(code)


def check_tree(measured_tree: str, expected_tree: str) -> bool:
    """Pure: the acceptance identity gate (test F)."""
    return measured_tree.strip().lower() == expected_tree.strip().lower() and len(expected_tree.strip()) == 40


def compare_record_to_mcp(record: dict, mcp_result: dict, chain_content_hash: str) -> dict:
    """Pure: correspondence between the EVE pre-action record and the MCP result.
    Every check is a separate predicate; nothing is derived from another."""
    return {
        "record_id_matches_header": record.get("record_id") == mcp_result.get("eve_record_id"),
        "record_chain_id_matches": record.get("chain_id") == mcp_result["eve"].get("chain_id"),
        "record_chain_content_hash_matches_chain": record.get("chain_content_hash") == chain_content_hash,
        "record_policy_hash_matches_mcp_policy_sha256":
            record.get("policy_content_hash") == mcp_result["policy"]["policy_content_sha256"],
        "record_result_equals_mcp_envelope": record.get("result") == mcp_result["eve"],
        "record_schema_version": record.get("record_schema_version"),
    }


def git_tree(checkout):
    git = shutil.which("git")
    if not git:
        stop(3, "git not on PATH")
    r = subprocess.run([git, "-C", checkout, "rev-parse", "HEAD", "HEAD^{tree}"], capture_output=True, text=True, timeout=60)
    if r.returncode:
        stop(3, f"git rev-parse failed: {r.stderr.strip()}")
    head, tree = r.stdout.split()
    return git, head, tree


async def mcp_call(mcp_url, arguments):
    async with streamable_http_client(mcp_url) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            tools = await s.list_tools()
            res = await s.call_tool(core.TOOL_NAME, arguments)
            return init, tools, res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eve-checkout", required=True)
    ap.add_argument("--expected-tree", required=True)
    ap.add_argument("--eve-base-url", required=True)
    ap.add_argument("--mcp-url", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--policy-ref", required=True)
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--eve-suite-python", default=None, help="run EVE's full pytest suite in the checkout with this interpreter")
    a = ap.parse_args(argv)

    rec = {"record_kind": "eve_mcp_phase1_acceptance", "record_schema_version": "eve-mcp-acceptance-1.0",
           "harness": {"version": HARNESS_VERSION, "sha256": sha256_file(os.path.abspath(__file__))},
           "started_utc": now_z(), "steps": {}}

    # 0 -- the operator read token must be usable BEFORE any EVE record is minted: a run that
    #      cannot be verified must not leave evaluated records behind. It travels in an HTTP
    #      header, so it must be ASCII without whitespace. Never written to the evidence record.
    token = os.environ.get("PRE_ACTION_READ_TOKEN", "")
    if not token.strip():
        stop(8, "PRE_ACTION_READ_TOKEN not set in this shell; operator verification is a Phase 1 gate")
    if not token.isascii() or any(c.isspace() for c in token):
        stop(8, "PRE_ACTION_READ_TOKEN must be ASCII without whitespace (HTTP header value); refusing to start")

    # 1 -- pinned EVE identity (hard STOP)
    checkout = os.path.abspath(a.eve_checkout)
    git, head, tree = git_tree(checkout)
    rec["steps"]["eve_identity"] = {"checkout": checkout, "head": head, "tree": tree, "expected_tree": a.expected_tree,
                                    "git_executable": git, "trusted_git_claim": "NONE (PATH git)"}
    if not check_tree(tree, a.expected_tree):
        stop(3, f"EVE checkout tree {tree} != expected {a.expected_tree}; live acceptance refused")

    # 2 -- external store root (this shell's view; the EVE process env is OPERATOR_ASSERTED)
    store = os.environ.get("EVE_RUNTIME_STORE_ROOT", "")
    if not store.strip():
        stop(3, "EVE_RUNTIME_STORE_ROOT is not set in this shell")
    store_abs = os.path.abspath(store)
    if os.path.commonpath([store_abs, checkout]) == checkout:
        stop(3, "EVE_RUNTIME_STORE_ROOT resolves inside the EVE checkout")
    rec["steps"]["runtime_store"] = {"root": store_abs, "external_to_checkout": True,
                                     "eve_process_env_claim": "OPERATOR_ASSERTED (process environment not readable from here)"}

    # 3 -- loopback
    for label, url in (("eve", a.eve_base_url), ("mcp", a.mcp_url)):
        host = urlsplit(url).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            stop(3, f"{label} url {url} is not loopback; Phase 1 acceptance requires loopback")
    rec["steps"]["loopback"] = {"eve_base_url": a.eve_base_url, "mcp_url": a.mcp_url}

    # 4 -- optional EVE full regression from the clone
    if a.eve_suite_python:
        r = subprocess.run([a.eve_suite_python, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=checkout,
                           capture_output=True, text=True, timeout=3600,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        tail = "\n".join(r.stdout.strip().splitlines()[-3:])
        rec["steps"]["eve_full_suite"] = {"python": a.eve_suite_python, "exit_code": r.returncode, "tail": tail,
                                          "stdout_sha256": hashlib.sha256(r.stdout.encode()).hexdigest()}
        if r.returncode != 0:
            stop(4, f"EVE full suite failed in the clone:\n{tail}")
    else:
        rec["steps"]["eve_full_suite"] = {"status": "NOT_EXECUTED_BY_HARNESS"}

    # 5 -- registry + policy identity
    file_sha, policies = core.load_policy_registry(a.registry)
    if a.policy_ref not in policies:
        stop(3, f"policy_ref {a.policy_ref} not in registry")
    policy = policies[a.policy_ref]
    rec["steps"]["policy"] = {"registry_file_sha256": file_sha, "policy_ref": a.policy_ref,
                              "policy_content_sha256": policy.policy_content_sha256}

    # 6 -- scenarios + EVE chain liveness + seal + verify
    with open(a.scenarios, "rb") as fh:
        scen = json.loads(fh.read().decode("utf-8"))
    rec["steps"]["scenarios_file"] = {"path": os.path.abspath(a.scenarios), "sha256": sha256_file(a.scenarios)}
    http = httpx.Client(base_url=a.eve_base_url, timeout=15, follow_redirects=False)
    sys.path.insert(0, checkout)
    from core.eve_chain.schema import EveChain   # read-only import for hash recomputation
    chains = {}
    for sc in scen["scenarios"]:
        cid = sc["chain_id"]
        g = http.get(f"/api/chain/{cid}")
        if g.status_code != 200:
            stop(5, f"chain {cid} not served by EVE (HTTP {g.status_code}); run build_scenario_chains.py --save first")
        d = g.json()
        recomputed = EveChain.from_dict(d).compute_content_hash()
        if recomputed != d.get("content_hash"):
            stop(5, f"chain {cid}: recomputed content_hash {recomputed} != stored {d.get('content_hash')}")
        s = http.post(f"/api/chain/{cid}/seal")
        if s.status_code != 200:
            stop(5, f"seal of {cid} failed HTTP {s.status_code}")
        v = http.get(f"/api/chain/{cid}/verify").json()
        if v.get("verify_status") != "VALID":
            stop(5, f"chain {cid} verify_status {v.get('verify_status')}")
        chains[sc["scenario_id"]] = {"chain_id": cid, "content_hash": recomputed, "overall_verdict": d.get("overall_verdict"),
                                     "action_gate": d.get("action_gate"), "seal_id": v.get("seal_id"),
                                     "chain_verify_status": v.get("verify_status"), "manifest_hash": v.get("manifest_hash")}
    rec["steps"]["chains"] = chains

    # 7 -- EVE's own fail-closed paths (direct HTTP, documents the contract; MCP refuses these earlier)
    r422 = http.post("/api/chain/pre-action", json={"action_context": {"probe": True}})
    r404 = http.post("/api/chain/pre-action", json={"chain_id": "EVE-MCP-NO-SUCH-CHAIN"})
    rec["steps"]["eve_fail_closed_direct"] = {
        "no_chain_id": {"http": r422.status_code, "pre_action_status": r422.json().get("pre_action_status"),
                        "verified_chain_outcome": r422.json().get("verified_chain_outcome"), "record_header": r422.headers.get("x-eve-record-id")},
        "unknown_chain": {"http": r404.status_code, "pre_action_status": r404.json().get("pre_action_status"),
                          "verified_chain_outcome": r404.json().get("verified_chain_outcome"), "record_header": r404.headers.get("x-eve-record-id")},
    }
    if not (r422.status_code == 422 and r404.status_code == 404 and r422.headers.get("x-eve-record-id") is None):
        stop(6, "EVE fail-closed transport contract not as measured (expected 422/404 without record header)")

    # 8 -- MCP calls against the real EVE
    results = {}
    for sc_id, ch in chains.items():
        init, tools, res = asyncio.run(mcp_call(a.mcp_url, {
            "chain_id": ch["chain_id"], "policy_ref": a.policy_ref,
            "action_context": {"agent_id": "eve-mcp-acceptance", "scenario": sc_id, "requested_by": "operator_harness"}}))
        if res.isError or res.structuredContent is None:
            stop(7, f"{sc_id}: MCP returned an error: {[c.text for c in res.content]}")
        out = res.structuredContent
        exp = EXPECTED[sc_id]
        if out["eve"]["pre_action_status"] != "evaluated" or out["eve"]["verified_chain_outcome"] != exp["verified_chain_outcome"] \
                or out["eve"]["customer_policy_outcome"] != exp["customer_policy_outcome"] or not out["eve_record_id"]:
            stop(7, f"{sc_id}: unexpected EVE outcome {out['eve']['verified_chain_outcome']}/{out['eve']['customer_policy_outcome']} record={out['eve_record_id']}")
        results[sc_id] = {"mcp_server": {"name": init.serverInfo.name, "version": init.serverInfo.version, "protocol": init.protocolVersion},
                          "tools": [t.name for t in tools.tools], "result": out}
    if results["CASE_A"]["result"]["eve_record_id"] == results["CASE_B"]["result"]["eve_record_id"]:
        stop(7, "CASE_A and CASE_B share a record id")
    # MCP refuses caller policy before EVE (live check of the security boundary)
    _, _, refused = asyncio.run(mcp_call(a.mcp_url, {"chain_id": chains["CASE_A"]["chain_id"], "policy_config": {"default_outcome": "allow"}}))
    if not refused.isError:
        stop(7, "MCP accepted caller-supplied policy_config")
    _, _, unknown = asyncio.run(mcp_call(a.mcp_url, {"chain_id": "EVE-MCP-NO-SUCH-CHAIN", "policy_ref": a.policy_ref}))
    if unknown.isError or unknown.structuredContent["transport"]["http_status"] != 404 or unknown.structuredContent["eve_record_id"] is not None:
        stop(7, "unknown chain through MCP did not pass EVE's 404 envelope through")
    rec["steps"]["mcp"] = {"cases": results, "caller_policy_config_refused": True,
                           "unknown_chain_404_passthrough": unknown.structuredContent["eve"]["pre_action_status"]}

    # 9 -- operator verification of the real records (gated route; token validated at step 0, never recorded)
    verification = {}
    for sc_id, r in results.items():
        rid = r["result"]["eve_record_id"]
        g = http.get(f"/api/chain/pre-action/records/{rid}", headers={"Authorization": f"Bearer {token}"})
        if g.status_code != 200:
            stop(8, f"{sc_id}: record {rid} not readable (HTTP {g.status_code})")
        view = g.json()
        corr = compare_record_to_mcp(view["record"], r["result"], chains[sc_id]["content_hash"])
        verification[sc_id] = {"record_id": rid, "verify_status": view.get("verify_status"),
                               "seal": view.get("seal"), "correspondence": corr}
        if view.get("verify_status") != "VALID" or not all(v is True for k, v in corr.items() if k != "record_schema_version"):
            stop(8, f"{sc_id}: record verification/correspondence failed: {view.get('verify_status')} {corr}")
    rec["steps"]["record_verification"] = verification
    rec["eve_instance_identity_claim"] = ("OPERATOR_DECLARED: EVE has no self-attesting identity endpoint; the "
                                          "tree identity above was measured from the checkout git objects, not from the running service")
    rec["completed_utc"] = now_z()
    rec["status"] = "PHASE1_ACCEPTANCE_PASS"
    os.makedirs(a.evidence_dir, exist_ok=True)
    out = os.path.join(a.evidence_dir, f"ACCEPTANCE_{rec['completed_utc'].replace(':', '')}.json")
    if os.path.exists(out):
        stop(9, f"evidence file exists: {out}")
    rec["record_sha256"] = core.canonical_sha256(rec)
    with open(out, "x", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"PHASE1_ACCEPTANCE_PASS evidence={out} record_sha256={rec['record_sha256']}")
    for sc_id, r in results.items():
        e = r["result"]["eve"]
        print(f"  {sc_id}: {e['verified_chain_outcome']} / {e['customer_policy_outcome']} record={r['result']['eve_record_id']} "
              f"verify={verification[sc_id]['verify_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
