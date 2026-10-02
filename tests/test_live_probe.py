"""i3_intake_live_probe: offline tests against a fake MCP session. No network, no EVE call."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

PROBE_PATH = Path(__file__).resolve().parent.parent / "tools" / "vps" / "i3_intake_live_probe.py"
spec = importlib.util.spec_from_file_location("i3_intake_live_probe", PROBE_PATH)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

V1, V2 = "EVA-CH-e8fcd04353baf54fab0d91d0", "EVA-CH-995bf4a9f7c53e97719380c9"
STEPS = [f"v1={V1}:ACTION_CHAIN_SUPPORTED:allow", f"v2={V2}:HUMAN_REVIEW_REQUIRED:escalate",
         f"v1_again={V1}:ACTION_CHAIN_SUPPORTED:allow"]


def answer(chain_id, verified, policy, record, status="evaluated"):
    return NS(isError=False, structuredContent={
        "eve": {"chain_id": chain_id, "pre_action_status": status, "verified_chain_outcome": verified,
                "customer_policy_outcome": policy},
        "eve_record_id": record, "transport": {"http_status": 200}, "policy": {"policy_content_sha256": "p"}})


class FakeSession:
    def __init__(self, answers, protocol="2025-11-25", server="eve-mcp", tools=("eve_pre_action",)):
        self.answers, self.protocol, self.server, self.tool_names = list(answers), protocol, server, tools
        self.calls = []

    async def initialize(self):
        return NS(protocolVersion=self.protocol, serverInfo=NS(name=self.server, version="1"))

    async def list_tools(self):
        return NS(tools=[NS(name=n) for n in self.tool_names])

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return self.answers.pop(0)


def good_answers():
    return [answer(V1, "ACTION_CHAIN_SUPPORTED", "allow", "EVE-PAR-LOCAL-000101"),
            answer(V2, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000102"),
            answer(V1, "ACTION_CHAIN_SUPPORTED", "allow", "EVE-PAR-LOCAL-000103")]


def run(session, steps=STEPS):
    return asyncio.run(P.probe(session, [P.parse_step(s) for s in steps]))


def test_step_arguments_are_strict():
    assert P.parse_step(STEPS[0]) == ("v1", V1, "ACTION_CHAIN_SUPPORTED", "allow")
    for bad in ("v1", f"v1={V1}:ACTION_CHAIN_SUPPORTED", f"V1={V1}:ACTION_CHAIN_SUPPORTED:allow",
                "v1=EVA CH:ACTION_CHAIN_SUPPORTED:allow", f"v1={V1}:action_chain_supported:allow",
                f"v1={V1}:ACTION_CHAIN_SUPPORTED:ALLOW", f"v1=:ACTION_CHAIN_SUPPORTED:allow"):
        with pytest.raises(P.ProbeArgError):
            P.parse_step(bad)


def test_the_three_step_run_passes_and_asks_only_eve_pre_action_with_the_pinned_policy():
    s = FakeSession(good_answers())
    out = run(s)
    assert out["stop"] is None and [x["ok"] for x in out["steps"]] == [True, True, True]
    assert [c[0] for c in s.calls] == ["eve_pre_action"] * 3
    assert [c[1] for c in s.calls] == [{"chain_id": V1, "policy_ref": P.POLICY_REF},
                                      {"chain_id": V2, "policy_ref": P.POLICY_REF},
                                      {"chain_id": V1, "policy_ref": P.POLICY_REF}]


def test_the_first_deviation_stops_before_any_further_evaluation():
    answers = good_answers()
    answers[0] = answer(V1, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000101")
    s = FakeSession(answers)
    out = run(s)
    assert out["stop"] and "expected ACTION_CHAIN_SUPPORTED/allow" in out["stop"]
    assert len(s.calls) == 1 and len(out["steps"]) == 1 and out["steps"][0]["ok"] is False


@pytest.mark.parametrize("bad", ["chain", "status", "no_record", "tool_error", "repeated_record"])
def test_every_kind_of_wrong_answer_is_a_stop(bad):
    answers = good_answers()
    if bad == "chain":
        answers[1] = answer(V1, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000102")
    elif bad == "status":
        answers[1] = answer(V2, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000102", status="chain_not_found")
    elif bad == "no_record":
        answers[1] = answer(V2, "HUMAN_REVIEW_REQUIRED", "escalate", "")
    elif bad == "tool_error":
        answers[1] = NS(isError=True, structuredContent=None)
    else:
        answers[1] = answer(V2, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000101")
    s = FakeSession(answers)
    out = run(s)
    assert out["stop"] and len(s.calls) == 2 and out["steps"][-1]["ok"] is False


@pytest.mark.parametrize("kw", [{"protocol": "2025-06-18"}, {"server": "something-else"},
                                {"tools": ("eve_pre_action", "extra")}])
def test_an_unexpected_server_stops_before_any_evaluation(kw):
    s = FakeSession(good_answers(), **kw)
    out = run(s)
    assert out["stop"] and s.calls == [] and out["steps"] == []


def test_record_is_self_hashed_written_on_stop_too_and_never_contains_the_bearer(tmp_path, monkeypatch, capsys):
    token = "SECRET-TOKEN-VALUE-1234567890"
    (tmp_path / "token").write_text(token, encoding="ascii")
    answers = good_answers()
    answers[2] = answer(V1, "HUMAN_REVIEW_REQUIRED", "escalate", "EVE-PAR-LOCAL-000103")   # v1 changed?!

    async def fake_live(token_file, steps):
        assert open(token_file, encoding="ascii").read() == token
        return await P.probe(FakeSession(answers), steps)

    monkeypatch.setattr(P, "_live", fake_live)
    ev = tmp_path / "ev"
    code = P.main(["--token-file", str(tmp_path / "token"), "--evidence-dir", str(ev),
                   *[x for s in STEPS for x in ("--step", s)]])
    assert code == 3
    (path,) = list(ev.glob("PROBE_*.json"))
    text = path.read_text(encoding="utf-8")
    assert token not in text and token not in capsys.readouterr().out
    rec = json.loads(text)
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    assert hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest() == rec["record_sha256"]
    assert rec["result"] == "PROBE_STOP" and rec["bearer"] == "PRESENT_NOT_RECORDED"
    assert [s["ok"] for s in rec["steps"]] == [True, True, False]


def test_duplicate_labels_are_refused_before_anything_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_live", lambda *a: pytest.fail("must not connect"))
    code = P.main(["--token-file", "x", "--evidence-dir", str(tmp_path / "ev"),
                   "--step", STEPS[0], "--step", STEPS[0].replace("v1=", "v1=", 1)])
    assert code == 2 and not (tmp_path / "ev").exists()
