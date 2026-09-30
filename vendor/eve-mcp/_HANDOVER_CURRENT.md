# 051_eve_mcp -- CURRENT HANDOVER (pointer)

```
NAVIGATION ONLY. NOT AUTHORITY.
Authority for EVE state: the EVE governed evidence/store chain.
Authority for this project's runs: the self-hashed records in evidence\ and FREEZE_MANIFEST_EVE_MCP_v1.json.
Resolved via TRACK_RESOLUTION_V1 (D:\EVE11\SOURCE_OF_TRUTH.md): PROJECT_POINTER_PATTERN.
```

## What this project is

`eve-mcp` -- the reusable EVE product boundary that exposes a real EVE pre-action
determination to external AI agents over MCP Streamable HTTP. One tool
(`eve_pre_action`), verbatim EVE envelope, operator-owned hash-pinned policy, fail
closed. It is an EVE product increment first; the Amazon Build, Ship, Shape entry is a
LATER, separate layer on top of the frozen v1 (no Amazon code lives here).

## Pinned EVE identity for this project

```
tag             eve-core-v1
tree            a698922c9fd740c4b114e572a626380abf1590a4   (authoritative identity)
peeled commit   ffe118c326e3d4ec4b194ddea0ba6c8d09d78f27
remote          refs/tags/eve-core-v1 = be46c3c0..., ^{} = ffe118c3...  (ls-remote 2026-09-30)
demo clone      D:\EVE_DEMO\eve-core-v1 (tree verified by the harness), store D:\EVE_DEMO\eve_store
rule            demo/acceptance EVE = fresh clone at the tag, external EVE_RUNTIME_STORE_ROOT,
                loopback only. NEVER the dirty working tree of D:\EVE11\eve-verified-grc,
                NEVER an unspecified main state, NEVER the older VPS state.
```

## State (measure before relying on it)

```
phase            PHASE 1 ACCEPTED 2026-09-30, PRODUCT FREEZE v1 PREPARED -- Git commit/tag/push PENDING OWNER
freeze manifest  FREEZE_MANIFEST_EVE_MCP_v1.json  record_sha256 dfedb266ad1bb7a3e7af257eb9dd761445efe328a66dee46cb2a1b74ff18128d
                 whole-file sha256 6194fe00489ea0804c5464a05e11ebd7086fdedffe77abbb5186d376f5d40b88 (14357 B)
acceptance       evidence\ACCEPTANCE_2026-09-30T122051Z.json  record_sha256 79698509e0d2...a4352635 (self-SHA verified)
                 CASE_A ACTION_CHAIN_SUPPORTED/allow  record EVE-PAR-LOCAL-000003 VALID
                 CASE_B HUMAN_REVIEW_REQUIRED/escalate record EVE-PAR-LOCAL-000004 VALID
                 EVE full suite in the clone 1293 passed (run by the harness)
anomaly          EVE-PAR-LOCAL-000001/000002 = aborted first harness run, NOT accepted records, left in place
tests            88 passed Windows (.venv, Python 3.11.9) + 88 passed Linux after freeze packaging; no source change in freeze
dependencies     requirements.lock.txt (sha256 50054a77...) = accepted environment; mcp 1.30.0 => MCP protocol 2025-11-25
eve-verified-grc UNMODIFIED by this project (rule: zero mutations unless a governed EVE act says so)
git              NOT YET a repository; exact procedure prepared (see freeze report); planned tag eve-mcp-v1
durable copy     PENDING OWNER: F:\lab\EVE_DURABILITY\eve_mcp_v1\2026-09-30\ (evidence set + manifest + accepted handover)
snapshot         _HANDOVER_2026-09-30_PHASE1_ACCEPTED.md holds every identity of the accepted state
```

## Read next

```
FREEZE_MANIFEST_EVE_MCP_v1.json          the frozen identity: inventory, hashes, dependencies, EVE pin, records, limitations
_HANDOVER_2026-09-30_PHASE1_ACCEPTED.md  all identities of the accepted state, known artefacts of the run
README.md                       integrator section, contract, routing rule, quickstart, limitations
policies\policy_registry_v1.json   operator policies, self-pinned (canonical sha256)
scenarios\scenarios_v1.json     declared CASE_A / CASE_B data (verdicts are never declared)
evidence\                       self-hashed run records; newest record = current state
```

## RECORDING PROTOCOL (this project)

1. Measure before writing: identities (EVE tree, file hashes) come from tool output,
   never from memory.
2. Every run of the builder or the acceptance harness writes ONE new self-hashed
   record with exclusive create; records are never rewritten or deleted.
3. Secrets never enter a record (PRE_ACTION_READ_TOKEN, API keys): identities and
   hashes only.
4. This pointer is rewritten LAST, after the immutable records it names exist; a new
   dated `_HANDOVER_<date>_<state>.md` is written before this pointer moves.
5. Git: this directory is its own repository with its own private remote; explicit
   file staging only (`git add -- <path>`), never `add -A`; nothing from this project
   is committed into `eve-verified-grc` or `eve-governance`; DUR-3 style off-disk copy
   of `evidence\` when a phase closes. Evidence files keep their on-disk bytes
   (.gitattributes: evidence/*.json -text).
6. Amazon-specific work (Alexa+ simulation, Strands/Bedrock agent, submission
   assets) goes in a separate layer/repository that DEPENDS on the frozen v1.

## Open after v1

```
- EVE self-attested installation identity (EVE capability map #8); until then OPERATOR_DECLARED
- MCP protocol 2026-07-28 (stateless core) when the official Python SDK ships it
- MCP auth (OAuth 2.1 + PRM) only for real Alexa+ onboarding
- container packaging (deferred to the Amazon deployment phase)
- agent-side deterministic action gate + A/B/C behaviour probe (BoundaryBench successor track)
- EVE-core declared-scenario chain construction (ADR-018 s9) to retire the resolve() mirror
```
