# EVA -- Evidence Verification Agent

**powered by EVE -- Evidence Verification Engine**

EVA is an AI agent that may *propose* consequential actions but never *authorises* them.
Before any consequential tool runs, a deterministic gate asks EVE for a real
pre-action determination over an existing evidence chain; only EVE's `allow` lets the
tool execute. Anything else -- pause, escalate, block, unknown, unreachable -- stops the
action, and EVA reports the outcome together with EVE's sealed record id.

```
User
 |
 v
EVA  (Strands Agents SDK + Amazon Bedrock model)   -- reasons, proposes an action
 |
 v
Deterministic EVE Gate  (plain Python, no model)   -- resolves the bound chain, asks EVE
 |
 v
EVE MCP v1  (vendor/eve-mcp, frozen)               -- one MCP tool: eve_pre_action
 |
 v
EVE  (eve-core-v1, private, loopback only)         -- verifies, evaluates policy, seals a record
 |
 v
allow    -> the tool executes; EVA reports the record id
anything -> the tool is cancelled; EVA escalates and reports the record id
```

EVA proposes. EVE decides. The gate enforces. EVA is not Alexa+ and does not claim to be;
the Alexa+ track submission demonstrates EVA through a self-hosted MCP server (EVE MCP v1)
and, in a later phase, a simulated Alexa+ experience built with our own tools.

## Immutable dependencies

| Dependency | Identity (tree is authoritative) | How it enters EVA |
|---|---|---|
| EVE MCP v1 | tag `eve-mcp-v1`, tree `cbdcd191710c472f7706a9487f31eef3cfd1821d`, commit `a0a5fe34...` | vendored at `vendor/eve-mcp`, verified by `tools/verify_vendor.py` |
| EVE core | tag `eve-core-v1`, tree `a698922c9fd740c4b114e572a626380abf1590a4`, commit `ffe118c3...` | never in this repository; runs behind EVE MCP on loopback |

Neither dependency is modified here. `tools/verify_vendor.py` recomputes the Git tree of
the vendored copy from its bytes (no git needed), checks the freeze manifest's self-hash
against the pinned value and every inventoried file against its SHA-256; it exits 0 only
when the vendored copy is byte-for-byte the frozen tag.

```
python tools/verify_vendor.py            # expected: VENDOR_VERIFY PASS ... tree cbdcd191...
```

## Phase 1 scope (this state of the repository)

- I1: repository skeleton, vendored EVE MCP v1, vendor verification, vendored test run.
- I2: hosted demo backend (EVE at eve-core-v1 + EVE MCP v1 behind TLS and a bearer token, EVE not exposed).
- I3: EVA on Strands + Bedrock with the deterministic gate; Case A / Case B via CLI.

Not in Phase 1: the simulated Alexa+ experience, video, open-source contribution, Devpost submission.

## Reproducing the vendored EVE MCP tests

```
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r vendor\eve-mcp\requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e vendor\eve-mcp --no-deps
.\.venv\Scripts\python.exe -m pytest vendor\eve-mcp\tests -q      # expected: 88 passed
```

The tests run against a fake-EVE fixture that reproduces the measured EVE contract; they are
unit evidence for the adapter, never acceptance evidence. Acceptance against the real pinned
EVE is recorded in `vendor/eve-mcp/evidence/` and `vendor/eve-mcp/FREEZE_MANIFEST_EVE_MCP_v1.json`.

## Claim boundaries

- EVE verifies the evidence chain and evaluates the operator-owned policy; EVA never sees or
  supplies the policy, never chooses the chain, never reinterprets the envelope.
- `customer_policy_outcome` is a policy outcome, never an EVE decision; `allow` is the only
  value that lets a consequential tool run.
- A VALID seal proves record integrity, not the truth of declared premises. Demo chains are
  synthetic declared data; the determinations and records are real.
- Not claimed: EVE-attested installation identity (it is OPERATOR_DECLARED), Bridge anchoring,
  any Alexa+ capability beyond a self-hosted MCP server, generalized production readiness.

## Provenance

EVE predates this work and is not part of this repository. EVE MCP v1 (2026-09-30), EVA, the
deterministic gate and the Amazon integration are new work created during the hackathon
submission period; every commit here carries its own date.
