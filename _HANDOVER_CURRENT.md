# 052_eva -- CURRENT HANDOVER (pointer)

```
NAVIGATION ONLY. NOT AUTHORITY.
Authority for EVE state: the EVE governed evidence/store chain.
Authority for EVE MCP v1: vendor/eve-mcp/FREEZE_MANIFEST_EVE_MCP_v1.json (record_sha256 dfedb266...) at tree cbdcd191...
Authority for EVA runs: self-hashed records under evidence\ (none yet).
Resolved via TRACK_RESOLUTION_V1 (D:\EVE11\SOURCE_OF_TRUTH.md): PROJECT_POINTER_PATTERN.
```

## What this project is

EVA -- Evidence Verification Agent, powered by EVE. A Strands + Bedrock agent that may
propose consequential actions; a deterministic gate asks EVE (through the frozen EVE MCP
v1) before any such tool runs and lets it run only on `allow`. Built for the Amazon
Build, Ship, Shape hackathon (Alexa+ track, self-hosted MCP server path; AWS Builder mini
challenge) and reusable afterwards as the EVE agent-gate pattern. EVA is not Alexa+.

## Immutable dependencies

```
EVE MCP v1   tag eve-mcp-v1  tree cbdcd191710c472f7706a9487f31eef3cfd1821d  commit a0a5fe34...  (vendor/eve-mcp)
EVE core     tag eve-core-v1 tree a698922c9fd740c4b114e572a626380abf1590a4  commit ffe118c3...  (never vendored; loopback behind EVE MCP)
rule         neither is modified here; tools/verify_vendor.py must PASS before any commit that touches vendor/
```

## State (measure before relying on it)

```
phase            PHASE 1 (I1-I3) GO 2026-09-30 -- I1 IN PROGRESS
I1               skeleton written; vendoring + verification + vendored tests + first commit PENDING OWNER commands
I2               hosted demo backend on the VPS -- NOT STARTED (measure port/process/nginx first; existing EVE/GRC untouched)
I3               EVA (Strands + Bedrock) + deterministic gate + CLI Case A/B -- NOT STARTED (Bedrock model access to be measured; STOP if none)
repo             D:\EVE11\Projects\052_eva  ->  https://github.com/elekto-energy/eva (private; owner-created)
devpost          New/Existing field UNTOUCHED; working default "Existing, but significantly updated", to be verified against the form text
```

## Read next

```
README.md                     EVA story, architecture, immutable dependencies, Phase 1 scope, claim boundaries
tools\verify_vendor.py        vendor identity check (git tree without git + manifest + inventory)
vendor\eve-mcp\               frozen EVE MCP v1 (README, contract, acceptance evidence, freeze manifest)
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
   after the records it names exist; a dated `_HANDOVER_<date>_<state>.md` precedes each move.
6. Claims: EVA proposes, EVE decides, the gate enforces. Never "EVA is Alexa+", never
   EVE-attested installation identity, never Bridge anchoring, never production readiness.

## Open

```
- Bedrock model id + region: to be measured in the owner's AWS account (I3 gate)
- VPS port/process/nginx for the demo backend: to be measured (I2 gate)
- Devpost New/Existing wording: to be verified from the form
- Phase 2: simulated Alexa+ experience, video, python-sdk open-source contribution, submission
```
