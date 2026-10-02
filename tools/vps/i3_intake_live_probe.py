"""i3_intake_live_probe.py -- live pre-action for intake-created chains through the PUBLIC EVE MCP surface.

Runs on the VPS in /opt/eva-demo/venv-mcp, like i2_remote_probe.py: every request traverses the public
hostname, TLS and the nginx bearer gate. The bearer is read from the token file and is never printed,
hashed or recorded.

  python i3_intake_live_probe.py --token-file FILE --evidence-dir DIR \
      --step v1=EVA-CH-...:ACTION_CHAIN_SUPPORTED:allow \
      --step v2=EVA-CH-...:HUMAN_REVIEW_REQUIRED:escalate \
      --step v1_again=EVA-CH-...:ACTION_CHAIN_SUPPORTED:allow

Every expected value is given explicitly; nothing is defaulted. Steps run in the given order and the
probe STOPS at the first unexpected answer, so no further pre-action evaluation is requested after a
deviation. Each tools/call is a real pre-action evaluation: EVE mints one sealed record per step.
The probe itself writes nothing but ONE self-hashed record PROBE_<ts>.json (exclusive create), which is
written whether the run passes or stops. Exit 0 = PROBE_PASS, 3 = PROBE_STOP, 2 = invalid arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sys

URL = "https://grc.eveverified.com/eva/mcp"
POLICY_REF = "eve-mcp-demo-policy-v1"
EXPECTED_PROTOCOL = "2025-11-25"
EXPECTED_SERVER = "eve-mcp"
LABEL_RE = re.compile(r"^[a-z0-9_]{1,32}$")
OUTCOME_RE = re.compile(r"^[A-Z_]{1,64}$")
POLICY_RE = re.compile(r"^[a-z_]{1,64}$")


class ProbeArgError(ValueError):
    pass


def parse_step(text: str) -> tuple:
    label, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or len(parts) != 3:
        raise ProbeArgError(f"--step must be LABEL=CHAIN_ID:VERIFIED_OUTCOME:POLICY_OUTCOME, got {text!r}")
    chain_id, want_verified, want_policy = parts
    if not LABEL_RE.match(label):
        raise ProbeArgError(f"label {label!r} must match {LABEL_RE.pattern}")
    if not chain_id or chain_id != chain_id.strip() or any(c.isspace() for c in chain_id) or len(chain_id) > 200:
        raise ProbeArgError(f"chain id {chain_id!r} is not a valid EVE MCP chain_id")
    if not OUTCOME_RE.match(want_verified) or not POLICY_RE.match(want_policy):
        raise ProbeArgError(f"expected outcomes in {text!r} are malformed")
    return label, chain_id, want_verified, want_policy


def check_call(step: tuple, res) -> tuple[dict, str | None]:
    """Return (observed fields, None) if the answer is exactly the expected one, else (observed, reason)."""
    label, chain_id, want_verified, want_policy = step
    if getattr(res, "isError", True) or getattr(res, "structuredContent", None) is None:
        return {"tool_error": True}, f"{label}: tool error or no structured content"
    sc = res.structuredContent
    eve = sc.get("eve", {}) if isinstance(sc.get("eve"), dict) else {}
    got = {"chain_id": eve.get("chain_id"), "pre_action_status": eve.get("pre_action_status"),
           "verified_chain_outcome": eve.get("verified_chain_outcome"),
           "customer_policy_outcome": eve.get("customer_policy_outcome"),
           "eve_record_id": sc.get("eve_record_id"),
           "http_status": (sc.get("transport") or {}).get("http_status"),
           "policy_content_sha256": (sc.get("policy") or {}).get("policy_content_sha256")}
    if got["chain_id"] != chain_id:
        return got, f"{label}: answered for chain {got['chain_id']!r}, asked {chain_id!r}"
    if got["pre_action_status"] != "evaluated":
        return got, f"{label}: pre_action_status {got['pre_action_status']!r} != 'evaluated'"
    if got["verified_chain_outcome"] != want_verified or got["customer_policy_outcome"] != want_policy:
        return got, (f"{label}: got {got['verified_chain_outcome']}/{got['customer_policy_outcome']}, "
                     f"expected {want_verified}/{want_policy}")
    if not isinstance(got["eve_record_id"], str) or not got["eve_record_id"]:
        return got, f"{label}: no EVE record id"
    return got, None


async def probe(session, steps: list[tuple]) -> dict:
    """Run the steps against an initialised MCP session; stop at the first deviation."""
    out = {"initialize": None, "tools_list": None, "steps": [], "stop": None}
    init = await session.initialize()
    out["initialize"] = {"protocolVersion": init.protocolVersion, "serverInfo_name": init.serverInfo.name,
                         "serverInfo_version": init.serverInfo.version}
    if init.protocolVersion != EXPECTED_PROTOCOL or init.serverInfo.name != EXPECTED_SERVER:
        out["stop"] = f"unexpected server: {out['initialize']}"
        return out
    tools = await session.list_tools()
    out["tools_list"] = [t.name for t in tools.tools]
    if out["tools_list"] != ["eve_pre_action"]:
        out["stop"] = f"tools/list {out['tools_list']} != ['eve_pre_action']"
        return out
    seen_records = set()
    for step in steps:
        label, chain_id, want_verified, want_policy = step
        res = await session.call_tool("eve_pre_action", {"chain_id": chain_id, "policy_ref": POLICY_REF})
        got, reason = check_call(step, res)
        if reason is None and got["eve_record_id"] in seen_records:
            reason = f"{label}: EVE record id {got['eve_record_id']} repeated"
        out["steps"].append({"label": label, "chain_id": chain_id, "expected": [want_verified, want_policy],
                             "observed": got, "ok": reason is None})
        if reason is not None:
            out["stop"] = reason
            return out
        seen_records.add(got["eve_record_id"])
    return out


def write_record(evidence_dir: str, steps: list[tuple], out: dict) -> tuple[str, dict]:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rec = {"record_kind": "eva_i3_intake_live_probe", "record_schema_version": "eva-intake-live-probe-1.0",
           "run_utc": ts, "surface": URL, "policy_ref": POLICY_REF, "bearer": "PRESENT_NOT_RECORDED",
           "requested_steps": [{"label": s[0], "chain_id": s[1], "expected": [s[2], s[3]]} for s in steps],
           **out, "result": "PROBE_PASS" if out["stop"] is None else "PROBE_STOP"}
    rec["record_sha256"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, f"PROBE_{ts}.json")
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path, rec


async def _live(token_file: str, steps: list[tuple]) -> dict:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    with open(token_file, "r", encoding="ascii") as fh:
        token = fh.read().strip()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        async with streamable_http_client(URL, http_client=client) as (r, w, _):
            async with ClientSession(r, w) as s:
                return await probe(s, steps)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--step", action="append", required=True)
    a = ap.parse_args(argv)
    try:
        steps = [parse_step(t) for t in a.step]
    except ProbeArgError as exc:
        print(f"STOP [2] {exc}")
        return 2
    labels = [s[0] for s in steps]
    if len(set(labels)) != len(labels):
        print("STOP [2] step labels must be unique")
        return 2
    out = asyncio.run(_live(a.token_file, steps))
    path, rec = write_record(a.evidence_dir, steps, out)
    for s in rec["steps"]:
        o = s["observed"]
        print(f"  {s['label']}: {o.get('verified_chain_outcome')} / {o.get('customer_policy_outcome')} "
              f"record={o.get('eve_record_id')} ok={s['ok']}")
    print(f"{rec['result']} evidence={path} record_sha256={rec['record_sha256']}")
    if rec["stop"]:
        print(f"STOP: {rec['stop']}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
