"""EVA CLI -- Del A: scripted proposer + deterministic gate + the REAL EVE MCP (no Bedrock).

  python -m eva.cli --case A      proposes SUP-EPSILON-001 -> high (chain EVE-MCP-DEMO-A-2026-001)
  python -m eva.cli --case B      proposes SUP-ZETA-002    -> high (chain EVE-MCP-DEMO-B-2026-001)

Writes ONE self-hashed run record per run to evidence/i3a/ (exclusive create). The mutable register
lives in runs/<ts>_<case>/ (gitignored); the seed in eva/data/ is never modified.
The bearer is read from EVA_MCP_BEARER_FILE (default D:\\EVE_SECRETS\\eva_mcp_bearer.txt) and never printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

from . import __version__, config
from .agent import build_agent
from .authorization import AuthorizationStore
from .eve_client import EveMcpClient
from .gate import EveGate
from .scripted_model import ScriptedModel
from .tools import SupplierRegister, build_tools

CASES = {"A": ("SUP-EPSILON-001", "high"), "B": ("SUP-ZETA-002", "high")}
REPO = config.PACKAGE_DIR.parent


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", required=True, choices=sorted(CASES))
    ap.add_argument("--model", default="scripted", choices=["scripted", "bedrock"])
    a = ap.parse_args(argv)
    if a.model != "scripted":
        print("STOP: Bedrock is not enabled in I3 Del A (separate owner GO for Del B).")
        return 3

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPO / "runs" / f"{ts}_{a.case}"
    run_dir.mkdir(parents=True, exist_ok=False)
    reg_path = run_dir / "supplier_register.json"
    shutil.copyfile(config.DATA_DIR / "supplier_register_seed.json", reg_path)
    register = SupplierRegister(reg_path)

    supplier_id, requested = CASES[a.case]
    tool_use_id = f"eva-{ts}-{a.case}"
    before_sha, before_rec = sha256_file(reg_path), register.get(supplier_id)

    store, executions = AuthorizationStore(), []
    gate = EveGate(EveMcpClient().pre_action, store)
    model = ScriptedModel([("tool", tool_use_id, "set_supplier_risk_status",
                            {"supplier_id": supplier_id, "risk_status": requested}),
                           ("text", "EVA: proposal handled; see the tool result for EVE's decision.")])
    agent = build_agent(model, gate, build_tools(store, register, executions))
    agent(f"Raise the risk status of supplier {supplier_id} to {requested}.")

    tool_results = [c["toolResult"] for m in agent.messages for c in m.get("content", []) if "toolResult" in c]
    after_sha, after_rec = sha256_file(reg_path), register.get(supplier_id)
    decision = gate.decisions[-1] if gate.decisions else None
    rec = {
        "record_kind": "eva_i3a_run", "record_schema_version": "eva-i3a-run-1.0", "run_utc": ts,
        "eva_version": __version__, "case": a.case,
        "model": {"kind": "scripted", "bedrock_invoked": False},
        "eve": {"mcp_url": config.EVE_MCP_URL, "policy_ref": config.POLICY_REF, "bearer": "PRESENT_NOT_RECORDED"},
        "proposal": {"tool": "set_supplier_risk_status", "tool_use_id": tool_use_id,
                     "args": {"supplier_id": supplier_id, "risk_status": requested}},
        "gate_decisions": gate.decisions_as_dicts(),
        "tool_executions": [{k: v for k, v in e.items() if k != "nonce"} for e in executions],
        "tool_results": [{"status": r.get("status"), "text": (r.get("content") or [{}])[0].get("text")} for r in tool_results],
        "register": {"before_sha256": before_sha, "after_sha256": after_sha, "changed": before_sha != after_sha,
                     "supplier_before": before_rec, "supplier_after": after_rec},
        "authorizations_left_unconsumed": store.pending_count(),
    }
    rec["record_sha256"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    ev_dir = REPO / "evidence" / "i3a"
    ev_dir.mkdir(parents=True, exist_ok=True)
    out = ev_dir / f"RUN_{ts}_{a.case}.json"
    with open(out, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")

    d = decision
    print(f"case {a.case}: gate={d.decision if d else None} reason={d.reason if d else None} "
          f"outcome={d.customer_policy_outcome if d else None} record={d.eve_record_id if d else None} "
          f"executed={any(e.get('executed') for e in executions)} register_changed={before_sha != after_sha}")
    print(f"run record {out} record_sha256={rec['record_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
