"""i2_remote_probe.py -- I2 gate: EVE MCP v1 reached through the PUBLIC authenticated surface.

Runs on the VPS in /opt/eva-demo/venv-mcp. Every request traverses the public hostname,
TLS and the nginx bearer gate (https://grc.eveverified.com/eva/mcp); origin host = the VPS.
The bearer is read from the 0600 token file and is never printed, hashed or recorded.

Hard assertions (any failure = exit 3, no evidence of PASS):
  initialize: protocolVersion == 2025-11-25, serverInfo.name == "eve-mcp"
  tools/list: exactly one tool, eve_pre_action
  Case A: isError False, pre_action_status evaluated, ACTION_CHAIN_SUPPORTED / allow, record id present
  Case B: isError False, pre_action_status evaluated, HUMAN_REVIEW_REQUIRED / escalate, record id present
  Case A record id != Case B record id
Note: each tools/call is a real pre-action evaluation; EVE mints one sealed record per case.
Writes ONE self-hashed record REMOTE_PROBE_<ts>.json (exclusive create).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "https://grc.eveverified.com/eva/mcp"
TOKEN_FILE = "/opt/eva-demo/nginx-bearer.txt"
EVID = "/opt/eva-demo/evidence"
POLICY_REF = "eve-mcp-demo-policy-v1"
EXPECTED_PROTOCOL = "2025-11-25"
EXPECTED_SERVER = "eve-mcp"
CASES = {
    "CASE_A": ("EVE-MCP-DEMO-A-2026-001", "ACTION_CHAIN_SUPPORTED", "allow"),
    "CASE_B": ("EVE-MCP-DEMO-B-2026-001", "HUMAN_REVIEW_REQUIRED", "escalate"),
}


def stop(msg: str) -> None:
    print(f"STOP: {msg}")
    sys.exit(3)


async def run() -> dict:
    with open(TOKEN_FILE, "r", encoding="ascii") as fh:
        token = fh.read().strip()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        async with streamable_http_client(URL, http_client=client) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                tools = await s.list_tools()
                calls = {}
                for case, (chain_id, _, _) in CASES.items():
                    res = await s.call_tool("eve_pre_action", {"chain_id": chain_id, "policy_ref": POLICY_REF})
                    calls[case] = res
    return {"init": init, "tools": tools, "calls": calls}


def main() -> int:
    out = asyncio.run(run())
    init, tools, calls = out["init"], out["tools"], out["calls"]
    rec = {"record_kind": "eva_i2_remote_probe", "record_schema_version": "eva-remote-probe-1.0",
           "run_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
           "surface": URL, "origin_host": "VPS 185.20.15.189 via public hostname + TLS + nginx bearer gate",
           "bearer": "PRESENT_NOT_RECORDED"}
    rec["initialize"] = {"protocolVersion": init.protocolVersion, "serverInfo_name": init.serverInfo.name,
                         "serverInfo_version": init.serverInfo.version}
    if init.protocolVersion != EXPECTED_PROTOCOL:
        stop(f"protocolVersion {init.protocolVersion} != {EXPECTED_PROTOCOL}")
    if init.serverInfo.name != EXPECTED_SERVER:
        stop(f"serverInfo.name {init.serverInfo.name} != {EXPECTED_SERVER}")
    names = [t.name for t in tools.tools]
    rec["tools_list"] = names
    if names != ["eve_pre_action"]:
        stop(f"tools/list {names} != ['eve_pre_action']")
    rec["cases"] = {}
    for case, (chain_id, want_outcome, want_policy) in CASES.items():
        res = calls[case]
        if res.isError or res.structuredContent is None:
            stop(f"{case}: tool error or no structured content")
        sc = res.structuredContent
        eve = sc.get("eve", {})
        got = {"chain_id": eve.get("chain_id"), "pre_action_status": eve.get("pre_action_status"),
               "verified_chain_outcome": eve.get("verified_chain_outcome"),
               "customer_policy_outcome": eve.get("customer_policy_outcome"),
               "eve_record_id": sc.get("eve_record_id"),
               "http_status": sc.get("transport", {}).get("http_status"),
               "policy_content_sha256": sc.get("policy", {}).get("policy_content_sha256")}
        rec["cases"][case] = got
        print(f"  {case}: {got['verified_chain_outcome']} / {got['customer_policy_outcome']} record={got['eve_record_id']} http={got['http_status']}")
        if got["chain_id"] != chain_id or got["pre_action_status"] != "evaluated" \
                or got["verified_chain_outcome"] != want_outcome or got["customer_policy_outcome"] != want_policy \
                or not got["eve_record_id"]:
            stop(f"{case}: unexpected {got}")
    if rec["cases"]["CASE_A"]["eve_record_id"] == rec["cases"]["CASE_B"]["eve_record_id"]:
        stop("Case A and Case B share a record id")
    rec["result"] = "REMOTE_PROBE_PASS"
    rec["record_sha256"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode()).hexdigest()
    path = os.path.join(EVID, f"REMOTE_PROBE_{rec['run_utc']}.json")
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"initialize: protocolVersion={init.protocolVersion} server={init.serverInfo.name}; tools/list={names}")
    print(f"REMOTE_PROBE_PASS evidence={path} record_sha256={rec['record_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
