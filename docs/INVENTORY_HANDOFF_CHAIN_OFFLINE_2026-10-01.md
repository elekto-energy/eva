# EVA -- Read-only inventory: handoff, agent chain, offline/resync (2026-10-01)

Purpose: before any EVA demo or product work depends on them, establish what already exists
under D:\EVE11 for (1) verified handoff between agents, (2) multi-step agent chains, (3) offline
operation with later resync, and (4) the OpsWatch boundary -- and, decisively, whether each one
exists in the frozen EVE that EVA actually uses (eve-core-v1, served to EVA through EVE MCP v1).

Scope: read-only. Nothing was built, changed, committed or deployed for this inventory.

Labels used:
- IMPLEMENTED              -- code exists on disk (path and sha256 given)
- DESIGN                   -- only a design/specification exists; no implementation found
- NOT_IN_EVE_CORE_V1       -- absent from the frozen core copy EVA's hosted EVE runs
- NOT_EXPOSED_BY_EVE_MCP   -- present in core, but not reachable through EVE MCP v1
- OWNER_STATED             -- stated by the owner; no record on disk
- FROM_MEMORY_NOT_REMEASURED -- taken from earlier session notes, not re-measured here

Reference points measured for this inventory:
- Frozen core copy inspected: D:\EVE11\staging\core_freeze_candidate (the isolated copy of the
  eve-core-v1 candidate tree used for the core-freeze regression). Its git tree identity was not
  re-measured in this inventory (FROM_MEMORY_NOT_REMEASURED: tree a698922c...). Its
  core\eve_chain\ holds 25 .py files.
- EVE MCP v1 surface: vendor/eve-mcp (tag eve-mcp-v1). eve_mcp/server.py list_tools() returns
  exactly one tool; core.TOOL_NAME = "eve_pre_action".

---

## 1. Verified Handoff (VHR)

Status: IMPLEMENTED (governance line) -- NOT_IN_EVE_CORE_V1 -- NOT_EXPOSED_BY_EVE_MCP

| Item | Path | sha256 | Bytes |
|---|---|---|---|
| Handoff contract | D:\EVE11\worktrees\eve-vhr-s1-001\core\eve_chain\verified_handoff.py | 935e322a462cf2f790d1660d3df7c01c16b9fac20fcf6436ae65e5b0d5fa0145 | 31719 |
| Orchestrator v0 | D:\EVE11\agents\eve_grc_agent\vhr_s2_takeover\orchestrator_v0.py | 2599ba7a7cd00710ed8ce285ed8d96039b2be06e512fdc1778cbb25e8018c731 | 7608 |
| Integration act spec | D:\EVE11\evidence\governed_actions\declarations\H_VHR_S1_INTEGRATION_003.md | 99ba470994cc63407998a3d21dbe51e762e7b61a257040750e8931d81d34c080 | 1924 |

Measured:
- verified_handoff.py, verified_handoff_store.py and tests/test_verified_handoff_contract.py exist
  in eve-vhr-s1-001 and in about sixty later worktrees (run0-*, run1-*, atlas-*, eve-platform-atlas-*).
- The git blob id of verified_handoff.py above is 3ba545383c48a7e31525d312d9adb719192751ed, which
  is exactly the blob the governed act VHR_S1_INTEGRATION_003 materialized (its spec names the
  three VHR-S1 blobs committed at 6567af69693f0e964068b2171327e3b7b148f81b).
- orchestrator_v0.py: verify_handoff -> frozen admission profile (integrity VERIFIED AND
  prior_binding EXACT_MATCH AND recipient admitted) -> ADVANCE or REFUSE; no LLM; the expected
  recipient role comes from the trusted invocation context, never from the candidate.
- The frozen core copy has no verified_handoff*.py in core\eve_chain\ -> NOT_IN_EVE_CORE_V1.
- EVE MCP v1 serves only eve_pre_action -> NOT_EXPOSED_BY_EVE_MCP.

FROM_MEMORY_NOT_REMEASURED: VHR-S2-b verdict PASS (N1 and N2 REFUSED with 0 writes, P ADVANCED).

Consequence for EVA: the hosted EVE behind /eva/mcp cannot verify a handoff between agents.

---

## 2. Multi-step agent chain

| Item | Status |
|---|---|
| EVE Chain plan (receipts / DAG verification) | DESIGN only. FROM_MEMORY_NOT_REMEASURED: owner decision 2026-08-18 put Phase 1+ on HOLD; no implementation found. |
| H7 cross-context binding (a determination is bound to its invocation I; advance requires EXACT_MATCH) | IMPLEMENTED in the frozen core copy -- NOT_EXPOSED_BY_EVE_MCP |
| G3 handling evidence (post-action evidence bound to a pre-action record, EXACT_MATCH) | IMPLEMENTED in the frozen core copy -- NOT_EXPOSED_BY_EVE_MCP |

| File (frozen core copy) | sha256 | Bytes |
|---|---|---|
| D:\EVE11\staging\core_freeze_candidate\core\eve_chain\h7_context_binding.py | 5eefcc48d56020153c6cdf57a739233abcf4bbf25220e30d939072ee8885a2f6 | 10917 |
| D:\EVE11\staging\core_freeze_candidate\core\eve_chain\handling_evidence.py | 29219d7538f3697eedaf14201c4ec578da901dc1281816282533d315534fedce | 13539 |

Consequence for EVA: with EVE MCP v1 as it is, a chain of agent actions can be governed only as a
sequence of independent eve_pre_action decisions. Each consequential step goes back through EVE;
nothing carries authority from one step to the next. That chain must not be described as a
verified handoff.

---

## 3. Offline operation and resync

| Location | Status |
|---|---|
| D:\EVE11\Projects\037_Marine\voyage_evidence (frozen contract v2) | IMPLEMENTED (local chain, continuation, gaps, external-anchor record) -- bridge anchoring NOT implemented -- NOT_IN_EVE_CORE_V1 |
| D:\EVE11\Projects\032_EVE_Rental\docs\offline-first-architecture.md | DESIGN only |
| D:\EVE11\core\V14\eve_offline, D:\EVE11\core\V14\verify_offline | Not relevant (see below) |

| File | sha256 | Bytes |
|---|---|---|
| 037_Marine\voyage_evidence\impl\chain_core_v2.py | cfc36f75d8259132323bba74aac4658e89cbb27306ed7a75082637ce99613e62 | 17695 |
| 037_Marine\voyage_evidence\docs\EVE_MARINE_EVIDENCE_v2.md | 95d6a02b15f2e271f49f35ad02f2f44d0a3d2948c91213739949eb17f7ba95f6 | 19714 |
| 032_EVE_Rental\docs\offline-first-architecture.md | 7fef04a38236184dfe9117d275dab554921874ec2cba760c23d428058061baaa | 23120 |

Measured, 037 (marine):
- chain_core_v2.py: ChainWriterV2 with signed checkpoints, continuation_of / continuation_reason
  after a reboot, and append_external_anchor(); verify_package_v2 fails on SEQUENCE_GAP,
  CONTINUATION_INVALID and ANCHOR_REF_INVALID.
- The v2 contract defines SOURCE_HEALTH_v2 (available / unavailable / stale / reconnected /
  restarted / clock_jump), EXTERNAL_ANCHOR_v2 (RFC3161_TSA, HTTPS_WITNESS, GIT_COMMIT, OTHER) and
  states that an offline period is anchored afterwards; package seal_status is
  LOCAL_INTEGRITY_ONLY or BRIDGE_ANCHORED.
- The verifier sets res.bridge_anchor_status = "NOT_BRIDGE_ANCHORED" unconditionally
  (chain_core_v2.py, line 413): anchoring to EVE Bridge is not implemented.

Measured, 032 (rental): the document specifies provisional seals offline, a sync engine that
links provisional to canonical seals, and conflict rules. Its own build checklist marks the sync
engine as not built. No sync, provisional or connectivity code exists anywhere in 032.

Not relevant: core\V14\eve_offline is a 985-byte REPL stub; core\V14\verify_offline verifies
download-package hashes without network access (it is not offline operation or resync).

Consequence for EVA: "offline operation with later EVE anchoring" must not be claimed. The local
half exists in 037; the anchoring half does not exist anywhere.

---

## 4. OpsWatch boundary

OWNER_STATED (2026-10-01): Jason McGill has accepted the boundary -- the agent asks EVE "may this
happen?" before an action; OpsWatch comes after the first real action ("what actually happened,
and may it be relied upon?") and before the next agent action.

Measured: the newest item in D:\EVE11\evidence\opswatch_pilot\ is the reply sent to Jason on
2026-09-22 (OPSWATCH_REPLY_SENT_2026-09-22.eml). Jason's acceptance is not saved there; until it
is saved as .eml in that folder it remains OWNER_STATED, not evidence.

---

## Summary

| Capability | Exists somewhere in EVE11 | In eve-core-v1 | Reachable through EVE MCP v1 |
|---|---|---|---|
| Pre-action decision (allow / escalate / ...) | yes | yes | yes (eve_pre_action) |
| Verified handoff between agents | IMPLEMENTED (governance line) | no | no |
| Invocation-bound determination (H7) | yes | yes | no |
| Post-action handling evidence (G3) | yes | yes | no |
| Chain / DAG verification | DESIGN, Phase 1+ on HOLD | no | no |
| Offline local chain + continuation | IMPLEMENTED (037) | no | no |
| Anchoring an offline period into EVE | not implemented | no | no |

Non-claims: this inventory does not establish that any listed implementation is correct,
complete, deployed or accepted beyond what is stated; it records presence, identity and location.
