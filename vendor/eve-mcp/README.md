# eve-mcp v1 -- EVE pre-action determination over MCP

`eve-mcp` is a thin, deterministic MCP boundary that lets an external AI agent ask a
real EVE instance for a **pre-action determination** without modifying EVE core.

```
agent  ->  MCP Streamable HTTP  ->  eve-mcp (this)  ->  EVE POST /api/chain/pre-action
                                                      <-  EVE envelope + X-EVE-Record-Id
agent  <-  EVE envelope VERBATIM + transport/policy/adapter metadata
```

## For external integrators

**What it is.** One MCP tool, `eve_pre_action`, in front of one pinned EVE instance. You
give it the id of an existing EVE evidence chain; EVE verifies the chain, evaluates it
against an operator-owned customer policy, persists a sealed pre-action record, and the
tool hands you EVE's answer unchanged plus the record id.

**What it does NOT do.** It does not construct chains, does not collect or judge evidence,
does not decide anything, does not default to allow, does not execute or block your
action, does not retry or cache determinations, and contains no language model. Your
agent framework acts (or refuses to act) on the outcome under its own deterministic gate.

**Who owns what.**
- EVE owns the determination (`eve.*` in the result) and the record id. The adapter never
  rewrites, reinterprets or upgrades any of it.
- The operator owns the policy. Callers select a registered, hash-pinned policy by
  `policy_ref`. Caller-supplied `policy_config` is refused before any EVE call.
- The caller owns `action_context`: correlation data that EVE echoes and never treats as
  evidence.

**Fail-closed.** Anything unknown, malformed, unreachable, timed out, unlisted or ambiguous
returns an MCP error result with a closed code and no envelope. There is no partial
success. `customer_policy_outcome` is a customer-policy outcome, never an EVE decision.

**Required deployment (Phase 1).** A fresh clone of EVE at the pinned identity below, an
EXTERNAL `EVE_RUNTIME_STORE_ROOT`, EVE and the adapter bound to loopback only (EVE's
pre-action route is ungated by contract and accepts caller policy, so the adapter must be
its only caller). No MCP authentication exists in Phase 1.

**Installation identity limitation.** EVE has no self-attesting identity endpoint. The
adapter reports `eve_instance.identity_basis = "OPERATOR_DECLARED"`: the tag/tree are the
operator's declaration, checked by the acceptance harness against the checkout's git
objects, never attested by the running EVE service.

## Pinned EVE identity

| | |
|---|---|
| tag | `eve-core-v1` |
| tree (authoritative) | `a698922c9fd740c4b114e572a626380abf1590a4` |
| peeled commit | `ffe118c326e3d4ec4b194ddea0ba6c8d09d78f27` |

## The tool: `eve_pre_action`

Input (closed object, `additionalProperties: false`):

| field | type | notes |
|---|---|---|
| `chain_id` | string, required | an EXISTING EVE chain (EVE chain_id mode; no chain construction) |
| `action_context` | object, optional | caller correlation data; echoed by EVE verbatim; **not evidence**, outside `inputs_hash` and outside the sealed record projection |
| `policy_ref` | string, optional | selects an **operator-registered, hash-pinned** policy; falls back to the configured default; **`policy_config` from the caller is refused before any EVE call** |

Result (`structuredContent`):

| key | origin | content |
|---|---|---|
| `eve` | EVE | the envelope **verbatim** (13 keys, plus `policy_rule_reason` on a matched rule) |
| `eve_record_id` | EVE | `X-EVE-Record-Id` header value on HTTP 200; `null` on 404/422 |
| `transport` | adapter | `http_status` (200/404/422), `endpoint_path`, `elapsed_ms` |
| `eve_instance` | operator | `declared_tag`, `declared_tree`, `identity_basis: OPERATOR_DECLARED` |
| `policy` | adapter | `policy_ref`, `policy_content_sha256` (EVE-comparable, see below) |
| `mcp` | adapter | `adapter_version`, `contract_version = eve-mcp-pre-action-1.0` |

Errors are tool results with `isError: true` and a closed code: `EVE_MCP_INPUT_INVALID`,
`POLICY_REF_UNKNOWN`, `POLICY_REF_REQUIRED`, `POLICY_PIN_MISMATCH`, `EVE_CONFIG_MISSING`,
`EVE_CONFIG_INVALID`, `EVE_UNREACHABLE`, `EVE_TIMEOUT`, `EVE_TRANSPORT_STATUS_UNSUPPORTED`,
`EVE_ENVELOPE_INVALID`, `EVE_OUTCOME_UNLISTED`, `EVE_RECORD_ID_ABSENT`.

### EVE fields (authoritative, measured from the pinned tree)

`verified_chain_outcome` is closed at five values -- `ACTION_CHAIN_SUPPORTED`,
`HUMAN_REVIEW_REQUIRED`, `SUPPORTED`, `PARTIAL`, `NO_ANSWER` -- and `null` on the
unevaluated paths. `customer_policy_outcome` is closed at six -- `allow`, `pause`,
`escalate`, `block`, `policy_not_configured`, `no_matching_policy_rule` -- and is the
**customer/operator policy outcome, never an EVE decision** (`policy_owner = customer`,
`enforcement_owner = customer_or_integrated_workflow`). `pre_action_status` is
`evaluated` (HTTP 200), `chain_reference_required` (422) or `chain_not_found` (404).
The adapter enforces these sets: an unlisted value fails closed.

### Integration routing rule (the integrator's, documented, NOT a field)

```
pre_action_status == "evaluated" and customer_policy_outcome == "allow"   -> may proceed
anything else (pause / escalate / block / policy_not_configured /
  no_matching_policy_rule / null / any error result)                       -> do not proceed
```

The adapter deliberately carries **no** `proceed`/`decision`/`safe` field: a second
decision surface is exactly what this boundary exists to avoid.

### Policy is operator-owned

`policies/policy_registry_v1.json` pins every policy with `policy_content_sha256` =
sha256 over the canonical JSON of `policy_config` (`sort_keys`, separators `,`/`:`,
`ensure_ascii=False`) -- the same canonicalization EVE uses for the `policy_content_hash`
it seals into the pre-action record. A pin mismatch is a **startup failure**. After a call,
`policy.policy_content_sha256` in the MCP result equals `policy_content_hash` in the EVE
record; the acceptance harness checks exactly that (established live on 2026-09-30).

## Configuration (all explicit; an unset value never means a default)

```
EVE_MCP_EVE_BASE_URL       http://127.0.0.1:8002      (loopback required unless EVE_MCP_ALLOW_NON_LOOPBACK=1)
EVE_MCP_TIMEOUT_SECONDS    10
EVE_MCP_DECLARED_TAG       eve-core-v1
EVE_MCP_DECLARED_TREE      a698922c9fd740c4b114e572a626380abf1590a4
EVE_MCP_POLICY_REGISTRY    <path>\policies\policy_registry_v1.json
EVE_MCP_DEFAULT_POLICY_REF eve-mcp-demo-policy-v1   (optional)
EVE_MCP_HOST               127.0.0.1
EVE_MCP_PORT               8765
```

Transport: stateless MCP Streamable HTTP at `/mcp`, protocol `2025-11-25` as shipped by
`mcp==1.30.0` (Alexa+ minimum); no sessions, no SSE resumability; no auth in Phase 1
(loopback only). Built on the low-level MCP `Server` because FastMCP was measured to
silently ignore unknown arguments such as `policy_config`.

## Reproducing the accepted environment

`pyproject.toml` pins the direct dependencies; `requirements.lock.txt` is the full
resolved set of the accepted environment (Python 3.11.9). Install from the lock:

```
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m pytest -q          # expected: 88 passed
```

## Quickstart (Windows, PowerShell 5.1; one command per line)

Shell 1 -- the real pinned EVE (leave running):
```
git -c core.autocrlf=false clone --branch eve-core-v1 https://github.com/elekto-energy/eve-verified-grc.git D:\EVE_DEMO\eve-core-v1
git -C D:\EVE_DEMO\eve-core-v1 rev-parse 'HEAD^{tree}'          # must print a698922c9fd740c4b114e572a626380abf1590a4
Set-Location D:\EVE_DEMO\eve-core-v1
& "D:\EVE11\venv_gpu\Scripts\python.exe" -m pytest -q -p no:cacheprovider   # expected 1293 passed
New-Item -ItemType Directory -Path D:\EVE_DEMO\eve_store -Force
$env:EVE_RUNTIME_STORE_ROOT = "D:\EVE_DEMO\eve_store"
$env:PRE_ACTION_READ_TOKEN = "<ASCII secret, no whitespace>"
& "D:\EVE11\venv_gpu\Scripts\python.exe" -m uvicorn grc_api:app --host 127.0.0.1 --port 8002
```

Shell 2 -- scenario chains, then the adapter (same `EVE_RUNTIME_STORE_ROOT`):
```
Set-Location D:\EVE11\Projects\051_eve_mcp
$env:EVE_RUNTIME_STORE_ROOT = "D:\EVE_DEMO\eve_store"
& "D:\EVE11\venv_gpu\Scripts\python.exe" scenarios\build_scenario_chains.py --eve-checkout D:\EVE_DEMO\eve-core-v1 --expected-tree a698922c9fd740c4b114e572a626380abf1590a4 --scenarios scenarios\scenarios_v1.json --evidence-dir evidence
```
That first run is PRINT_ONLY: it proves the composition mirror equals EVE's `resolve()`
on the canonical fixtures and shows the engine-derived verdicts without touching the
store. Only when both cases print `expected_met=True`, run the same command with
`--save` appended (the instrument never overwrites an existing chain). Then:
```
.\.venv\Scripts\python.exe -m pytest -q          # expected 88 passed
$env:EVE_MCP_EVE_BASE_URL = "http://127.0.0.1:8002"; $env:EVE_MCP_TIMEOUT_SECONDS = "10"; $env:EVE_MCP_DECLARED_TAG = "eve-core-v1"; $env:EVE_MCP_DECLARED_TREE = "a698922c9fd740c4b114e572a626380abf1590a4"; $env:EVE_MCP_POLICY_REGISTRY = "D:\EVE11\Projects\051_eve_mcp\policies\policy_registry_v1.json"; $env:EVE_MCP_DEFAULT_POLICY_REF = "eve-mcp-demo-policy-v1"; $env:EVE_MCP_HOST = "127.0.0.1"; $env:EVE_MCP_PORT = "8765"
.\.venv\Scripts\python.exe -m eve_mcp.server
```

Shell 3 -- acceptance against the real EVE (`EVE_RUNTIME_STORE_ROOT` and the SAME
`PRE_ACTION_READ_TOKEN` as shell 1 exported; the harness refuses to start otherwise):
```
Set-Location D:\EVE11\Projects\051_eve_mcp
.\.venv\Scripts\python.exe acceptance\run_acceptance.py --eve-checkout D:\EVE_DEMO\eve-core-v1 --expected-tree a698922c9fd740c4b114e572a626380abf1590a4 --eve-base-url http://127.0.0.1:8002 --mcp-url http://127.0.0.1:8765/mcp --registry policies\policy_registry_v1.json --policy-ref eve-mcp-demo-policy-v1 --scenarios scenarios\scenarios_v1.json --evidence-dir evidence --eve-suite-python D:\EVE11\venv_gpu\Scripts\python.exe
```
The harness STOPs on the first unestablished condition and otherwise writes a self-hashed
evidence record (identities and hashes only; the read token is never written).

## Accepted state (Phase 1, 2026-09-30)

Live acceptance against tree `a698922c...`: Case A `ACTION_CHAIN_SUPPORTED` / `allow`
(record `EVE-PAR-LOCAL-000003`, VALID), Case B `HUMAN_REVIEW_REQUIRED` / `escalate`
(record `EVE-PAR-LOCAL-000004`, VALID), EVE full regression 1293 passed inside the clone.
Evidence: `evidence/ACCEPTANCE_2026-09-30T122051Z.json`; every identity is in
`FREEZE_MANIFEST_EVE_MCP_v1.json`. Records `EVE-PAR-LOCAL-000001/000002` in the demo store
were minted by an aborted first harness run and are not accepted records; they were left
in place, never rewritten.

## Claim boundaries

- EVE verifies the chain; the customer policy maps the verified outcome; the
  organisation (or the calling agent framework, under its own deterministic gate) acts.
- A VALID seal proves record integrity, never the truth of customer-declared premises.
- Local seals are not Bridge anchoring; nothing here is "independently verified".
- Case A/B chains are synthetic demonstration data; the evaluation records are real.

## Out of scope in v1

Amazon/Alexa/Bedrock/Strands code, OpsWatch, BoundaryBench, Atlas changes, any
mutation of `eve-verified-grc`, MCP auth, containers, MCP protocol 2026-07-28.
