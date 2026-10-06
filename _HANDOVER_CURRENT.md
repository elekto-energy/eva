# 052_eva -- CURRENT HANDOVER (pointer)

```
NAVIGATION ONLY. NOT AUTHORITY.
Authority for EVE state: the EVE governed evidence/store chain.
Authority for EVE MCP v1: vendor/eve-mcp/FREEZE_MANIFEST_EVE_MCP_v1.json (record_sha256 dfedb266...) at tree cbdcd191...
Authority for EVA runs: self-hashed records under evidence\.
Resolved via TRACK_RESOLUTION_V1 (D:\EVE11\SOURCE_OF_TRUTH.md): PROJECT_POINTER_PATTERN.
```

**This file is a pointer. It is the only file in this track that moves.** It names the current
handover with the identity measured when this pointer was written. Measure it before relying on it.
If the disk differs: STOP and report.

## CURRENT HANDOVER

```
_HANDOVER_2026-10-06_052_S1LITE-TARGET-CLOSED.md
426b688520f18460b3c4591656f07c3807a6db2b4e0699d479de3497172715e0   17573
```

```
S1-lite / PRE    CLOSED; Target Identity IMPLEMENTED + LIVE VERIFIED + SEALED
                 closing commit 42ec356d6cf2423526614527cda48ad9534bec91 (owner decision 2026-10-06)
submission       Amazon presentation/submission PARKED (owner decision 2026-10-06)
DURING           NEXT, NOT STARTED
track            self-contained project track; no Atlas mutation (owner decision 2026-09-30, reaffirmed 2026-10-06)
```

## What this project is

EVA -- Evidence Verification Agent, powered by EVE. EVA may propose consequential actions; a
deterministic gate asks EVE (through the frozen EVE MCP v1) before any such tool runs and lets it
run only on `allow`. EVA proposes, EVE decides, the gate enforces. EVA is not Alexa+.

## Immutable dependencies

```
EVE MCP v1   tag eve-mcp-v1  tree cbdcd191710c472f7706a9487f31eef3cfd1821d  commit a0a5fe34...  (vendor/eve-mcp)
EVE core     tag eve-core-v1 tree a698922c9fd740c4b114e572a626380abf1590a4  commit ffe118c3...  (never vendored; loopback behind EVE MCP)
rule         neither is modified here; tools/verify_vendor.py must PASS before any commit that touches vendor/
```

## Read next

```
_HANDOVER_2026-10-06_052_S1LITE-TARGET-CLOSED.md   final S1-lite model: target identity, coverage boundary, three baselines, live results
evidence\s1lite_target_live\S1LITE_TARGET_RUN_INDEX_2026-10-06.json  target-bound live run (record_sha256 0787b508...)
_HANDOVER_2026-10-06_052_S1LITE-CLOSED.md          S1-lite as it stood at 1199f22 (before Target Identity); history
docs/DESIGN_S1LITE_VERIFIED_DELEGATION_2026-10-06.md  S1-lite design at 1199f22, provenance-labelled (not updated for Target Identity)
evidence\s1lite_live\S1LITE_RUN_INDEX_2026-10-06.json  historical S1-lite live run (record_sha256 878c1ca9...)
docs\DECISION_D4_HUMAN_REVIEW_2026-10-02.md        locked human-review semantics (R1-R7)
docs\DECISION_D5_CUSTOMER_CHAIN_BINDING_2026-10-02.md  locked chain-binding semantics (B1-B13)
README.md                                          EVA story and claim boundaries (not yet updated for S1-lite)
vendor\eve-mcp\                                    frozen EVE MCP v1
```

## RECORDING PROTOCOL (this project)

1. Measure before writing: identities (trees, hashes, model ids, ports) come from tool output, never from memory.
2. vendor/ is byte-identical to tag eve-mcp-v1; any drift = STOP. It is refreshed only by a
   new frozen EVE MCP tag, recorded here with tree id.
3. Every EVA run that produces acceptance-style evidence writes ONE new self-hashed record with
   exclusive create under evidence\; records are never rewritten.
4. Secrets never enter the repository or a record: bearer tokens, PRE_ACTION_READ_TOKEN, AWS
   credentials live in environment variables and the operator's testing instructions only.
5. Git: explicit staging by path, never add -A; this pointer moves LAST, in its own commit,
   after the records it names exist; a dated `_HANDOVER_<date>_052_<TOPIC>.md` precedes each move
   and is never rewritten.
6. Claims: EVA proposes, EVE decides, the gate enforces. Never "EVA is Alexa+", never
   EVE-attested installation identity, never Bridge anchoring, never production readiness.

## Retained handovers

```
_HANDOVER_2026-10-06_052_S1LITE-TARGET-CLOSED.md   426b688520f18460b3c4591656f07c3807a6db2b4e0699d479de3497172715e0   17573   (current)
_HANDOVER_2026-10-06_052_S1LITE-CLOSED.md          63cf9e2b33df1bf613e7a075ea5137c6aec8ef48376198e3c4091acbf3ff7221   11256
_HANDOVER_2026-09-30_052_I2-CLOSED.md              cf1360ee659dbc112996b6c77853dd2777babf4d655e9ac5249b688b6b21925b    6862
```
