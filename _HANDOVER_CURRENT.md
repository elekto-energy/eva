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
_HANDOVER_2026-09-30_052_I2-CLOSED.md
cf1360ee659dbc112996b6c77853dd2777babf4d655e9ac5249b688b6b21925b   6862
```

```
I1               CLOSED (owner decision 2026-09-30)
I2               CLOSED (owner decision 2026-09-30) -- evidence\i2\I2_CLOSURE_2026-09-30.json record_sha256 be1fb1fd...
I3               NOT_STARTED -- read-only AWS discovery blocked: no AWS credentials on the workstation (owner-reported)
main at snapshot 95bb7392d2fb4065a27ea931b1bf7a99769439cf (ls-remote 2026-09-30)
track            self-contained project track; no Atlas mutation (owner decision 2026-09-30)
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
_HANDOVER_2026-09-30_052_I2-CLOSED.md   state, identities, owner decisions and deviations at 2026-09-30
evidence\i2\I2_CLOSURE_2026-09-30.json  I2 gates, evidence inventory, instrument hashes
README.md                               EVA story, architecture, immutable dependencies, claim boundaries
tools\verify_vendor.py                  vendor identity check (git tree without git + manifest + inventory)
tools\vps\                              I2 instruments (backend steps, nginx diagnosis, remote probe)
vendor\eve-mcp\                         frozen EVE MCP v1
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
(none earlier; _HANDOVER_2026-09-30_052_I2-CLOSED.md is the first dated handover of this track)
```
