# HANDOVER — PROJECT 052_eva — 2026-10-06 — S1-lite (PRE) CLOSED

```
CLASS    NAVIGATION ARTIFACT (PROJECT TRACK)
STATUS   FROZEN SNAPSHOT
DATE     2026-10-06
```

**HANDOFF MAY POINT TO STATE. HANDOFF MUST NOT ASSERT CURRENT STATE.**

Every identity below was measured on 2026-10-06 in the session that wrote this file, unless it is
labelled OWNER_DECISION, OWNER_REPORTED or NOT_REMEASURED. Measure again before relying on it. If the
disk or a remote differs: STOP and report. This file is immutable; a later state gets a later dated
handover.

Predecessor: `_HANDOVER_2026-09-30_052_I2-CLOSED.md` (sha256 cf1360ee659dbc112996b6c77853dd2777babf4d655e9ac5249b688b6b21925b,
6862 B, as named by the pointer before this act).

---

## 0. READ THIS FIRST

```
S1-lite / PRE        CLOSED at 1199f223b368b5e871781a4f3032d0be8942c1b4   (OWNER_DECISION 2026-10-06)
S1-lite documentation CLOSED with this handover + docs/DESIGN_S1LITE_VERIFIED_DELEGATION_2026-10-06.md
Amazon presentation / submission   PARKED   (OWNER_DECISION 2026-10-06; deadline 23 Oct 2026 12:00 PT)
DURING               NEXT, NOT STARTED -- not designed, not implemented anywhere in this track
Atlas                deliberately outside the 052 track; UNCHANGED (OWNER_DECISION 2026-09-30, reaffirmed 2026-10-06)
README.md            UNCHANGED in this act; still to be rewritten for the submission
```

---

## 1. WHAT THIS PROJECT IS

EVA -- Evidence Verification Agent, powered by EVE. EVA may propose consequential actions; a
deterministic gate asks EVE (through the frozen EVE MCP v1) before any such action and lets it run
only on `allow`. EVA proposes, EVE decides, the gate enforces. EVA is not Alexa+.

```
EVE MCP v1   tag eve-mcp-v1   tree cbdcd191710c472f7706a9487f31eef3cfd1821d   (vendored at vendor/eve-mcp; not modified)
EVE core     tag eve-core-v1  tree a698922c9fd740c4b114e572a626380abf1590a4   (never vendored; not modified)
```

---

## 2. REPOSITORY AT THIS SNAPSHOT

```
local            D:\EVE11\Projects\052_eva
remote           https://github.com/elekto-energy/eva.git (private)
main             1199f223b368b5e871781a4f3032d0be8942c1b4
                 git ls-remote origin refs/heads/main = 1199f223b368b5e871781a4f3032d0be8942c1b4
working tree     clean before this act (git status --short empty, measured 2026-10-06)
```

### Commit chain since the predecessor (git log 95bb7392d2fb4065a27ea931b1bf7a99769439cf..HEAD, 25 commits)

Subjects are given only where they were read from `git log` output in this act; for the others use
`git log` (NOT_REMEASURED here).

```
1199f223b368b5e871781a4f3032d0be8942c1b4 2026-10-06  Evidence: S1-lite inc 4 live run (scripted proposer, not Nova) ...
0520506aebdc2c727c19a573361b3057ffc14a3d 2026-10-06  EVA S1-lite inc 3: delegation server ... (A) ... (A') ... 'Why didn't you book it?' ...
ce58fa26a06582eccfe323f8410bf80372a97b6e 2026-10-06  EVA S1-lite inc 2: DW evidence declarations (D-beta) + operator CLI (D-alpha) ...
055f047e8b7e265412da5718d248a7b5fba7e819 2026-10-06  EVA S1-lite inc 1: Verified Delegation core ...
2e94f26a51d5ff28a87809a36cb041fe7152c531 2026-10-06  EVA cli_bedrock: --evidence-dir and start-up STOP on a closed evidence package ...
42ffa4e3bdf5ec53f8493d2a1131fcc91e022296 2026-10-06  EVA evidence: i3b Nova runs 2026-10-06 vs eve-core-v1 a698922c ...
932f5d90ae480470cfd132439d38184fa9a82a50 2026-10-03  EVA Act 4 UI: history, review panel and verified audit view ...
e5e75de7df4b25bd218f0b686d9692a789ab41f3 2026-10-02  EVA evidence: real v1/v2 run 2026-10-02 vs eve-core-v1 a698922c ...
3c79141509d36a14ddf63c30aef85b54e437f7af 2026-10-02
a3fd06dc50595fd66d026b7079994affc71ffefd 2026-10-02
96c33601645a0e224bbad665310e3eec719bd3ac 2026-10-02
a434b3e623784a5f24524c187e25b1b127558c1d 2026-10-02
26c18b6960f804a716465d4021fde14cb27cafb9 2026-10-02
1e0b77d5c5c64207405e30f0f8fdb797243415c9 2026-10-02
9d18f8b77ecfe127d91d70c0c26eb29176cabc40 2026-10-02
f6f8ad9f3ee6df980bee45a9e0d9d65e23814f31 2026-10-02
e961c5a1ca0e1f4f7d1c3a5f8df6622a1b9bb812 2026-10-01
c714e22322fa5478004a486963b73114f03b4de4 2026-10-01
66830e15e9163e6993f0561feb54f21a3b875864 2026-09-30
8c38fdfb68db6ba95a925dd038fe215b7a03ce87 2026-09-30
7f6b8710c904e1dbc246b58ec99cfb0e85295b43 2026-09-30
f7b36e514782251b65cad08f4721b1055d8c1d65 2026-09-30
c4097185f8b206dc4932eaf2d4c2afe17c92ed63 2026-09-30
6dba18e8cbbba73e25dc7f3ee915dbdd28f5a6e1 2026-09-30
f482216b584a661f2284e1b3a5c80e57a86550b1 2026-09-30
```

### Regression (measured on the workstation at 0520506; 1199f22 adds evidence files only)

```
with EVA_EVE_CHECKOUT=D:\EVE_DEMO\eve-core-v1   248 passed
without                                         228 passed, 20 skipped
frozen I3A boundary                             verify_frozen_boundary() == FROZEN_I3A_BOUNDARY
```

### Evidence packages closed by a run index (measured: *_RUN_INDEX_* present)

```
evidence/demo_live/DEMO_LIVE_RUN_INDEX_2026-10-02.json
evidence/intake_live/INTAKE_LIVE_RUN_INDEX_2026-10-02.json
evidence/i3b/I3B_RUN_INDEX_2026-10-06.json
evidence/s1lite_live/S1LITE_RUN_INDEX_2026-10-06.json      record_sha256 878c1ca9ba8003493c9b3d93f6c632c4c3abaaccd094718407ff99b0806d04d4
```

A closed package is never appended to: the web servers and the declaration CLI refuse a directory
holding a run index. `evidence/i2` and `evidence/i3a` carry closure records instead of a run index
(NOT_REMEASURED here). `evidence/i4` is the supplier demo's default runtime directory.

---

## 3. S1-LITE "VERIFIED DELEGATION DEMO v1" — CLOSED

Design, as implemented, with per-statement provenance:
`docs/DESIGN_S1LITE_VERIFIED_DELEGATION_2026-10-06.md`
(sha256 76717c2cff7929a102850d80bc96a3532891207cd81b1e25f442244f15e03951, 14247 B).

```
inc 1  055f047  mandate/authorization records (read-back + human confirmation), deterministic check,
                separate booking gate (path a), consequence registry + mandatory invariant
inc 2  ce58fa2  D-beta declarations from confirmed records, D-alpha operator CLI, intake action class,
                audit subject key
inc 3  0520506  delegation server (path i, app.py untouched), human-only confirmation route,
                (A) eva/binding.py, (A') eva_review/review.py, "Why didn't you book it?"
inc 4  1199f22  live run against the hosted demo EVE + bindings dishwasher_v1/v2
```

### Live run 2026-10-06 (EVIDENCE: evidence/s1lite_live)

```
proposer   scripted (no LLM). The run does NOT claim that Amazon Nova performed S1-lite.
v1         mandate USD 200 -> DW-v1 EVA-CH-e1698b4b7d2963f272e1692a (APPROVAL_SCOPE_MISMATCH)
           -> EVE-PAR-LOCAL-000035 escalate, gate DENY, nothing booked -> "why" ESTABLISHED
v2         confirmed authorization USD 275 -> DW-v2 EVA-CH-6fb7fe20ec7762db7025c829 (SUPPORTED,
           supersedes v1) -> new process -> EVE-PAR-LOCAL-000036 allow, booked exactly once
history    000035 ESCALATE / NOT EXECUTED and 000036 ALLOW / EXECUTED side by side; both audits VERIFIED
D-1        unplanned non-consequential turn TURN_20261006T170835614852Z_1.json; cause NOT_ESTABLISHED;
           no EVE call, no PAR, no confirmed record; retained unchanged
```

---

## 4. HOSTED DEMO BACKEND (VPS) — measured 2026-10-06 after the run

```
EVE checkout     /opt/eva-demo/eve-core-v1  tree a698922c9fd740c4b114e572a626380abf1590a4, 0 dirty files
services         eva-eve active, eva-mcp active
store            chains.json             9a4d2aaa38f8f023b5191a2acbe17ad72d572978b55902d6716c0b9baceee181   57127 B   6 chains
                 pre_action_records.json c9eac484687d29d99501c6ed8e72f999392b04e62d62bfe2d602f89805f1c73a  137903 B  36 records
                 (store holds exactly these two files)
next PAR id      expected EVE-PAR-LOCAL-000037 -- an expectation, to be measured
added this run   /opt/eva-demo/eva-intake-dw (repo intake code + builder copy d11c2484...)
                 /opt/eva-demo/incoming/dw_s1lite, /opt/eva-demo/evidence/dw_intake
untouched        /opt/eva-demo/eva-intake (declaration.py 683c8010..., measured)
public surface   https://grc.eveverified.com/eva/mcp (bearer); must stay up through judging (OWNER_DECISION)
```

---

## 5. OWNER DECISIONS RECORDED UP TO 2026-10-06 (this track)

```
D4 human review (docs/DECISION_D4_HUMAN_REVIEW_2026-10-02.md) and D5 customer chain binding
  (docs/DECISION_D5_CUSTOMER_CHAIN_BINDING_2026-10-02.md) are locked; S1-lite changed neither
S1-lite constraints: EVE core, EVE MCP v1 and the I3A files byte-frozen; gate path (a); one synthetic
  firm and offer; one "why" question; read-back + explicit human confirmation for mandate and approval;
  no real providers, telephony, payments, calendars, execution monitoring or Q6
increment 3: path (i); (A) eva/binding.py and (A') eva_review/review.py approved as narrow changes
increment 4: scripted proposer; deviation D-1 retained, no re-run
S1-lite implementation CLOSED; documentation act (this handover + design doc + pointer) authorised;
  Atlas and README not touched; no product code, tests, evidence or EVE changed in this act
DURING: NEXT, NOT STARTED. First step READ-ONLY inventory of Q6, Authority Role, the Governed Action
  chain and ADR-021 before any EVE_GOVERNED_EXECUTION_DURING_v0.1.md; the design question goes to
  Maxim before the contract is frozen
Amazon material may name DURING as the next architectural step, never as implemented
a Nova run of S1-lite, if made, is a separate, separately labelled run
```

---

## 6. OPEN ITEMS (not started unless stated)

```
Amazon submission    PARKED: video (new directory, fresh baseline), README + testing instructions +
                     judge token, submission text, friction log, five product-feedback questions,
                     repository sharing with the reviewer accounts at submission
AWS                  credits form deadline 21 Oct 2026 (OWNER_REPORTED); reply to support case
                     179092376300496 drafted, sending NOT_ESTABLISHED; Business Support+ downgrade pending
Nova on S1-lite      not run; optional, separate run
DURING               not started
```

---

## 7. DEVIATIONS, RECORDED — NOT CORRECTED

```
HANDOVER_LAG
  25 commits (95bb739 -> 1199f22) were made while _HANDOVER_CURRENT.md still named the 2026-09-30
  handover ("I3 NOT_STARTED"). This handover and the following pointer commit close that gap; history
  is not rewritten.

UNPLANNED_EXISTING_FILE_CHANGES (increment 3)
  eva/binding.py (A) and eva_review/review.py (A') were not listed in the increment design; the build
  stopped on each and continued only after owner approval.

D-1 (increment 4)
  See section 3. Cause NOT_ESTABLISHED.
```

---

## 8. SEPARATE, NOT PART OF THIS TRACK

```
SECURITY   The predecessor recorded the X-Trinity-Key / X-Ctrl-Energy-Key exposure (2026-09-30) and a
           separate rotation act. Its status is NOT_REMEASURED here.
```

---

## 9. NON-CLAIMS

```
this handover asserts no current state; it points at state measured on 2026-10-06
formal closure status of I3A, I3B, I4 and Act 4 as acts is NOT_REMEASURED here; their commits and
  records exist as listed
no DURING or POST capability exists in this track
Nova has not performed S1-lite
EVE installation identity on the VPS remains OPERATOR_DECLARED
EVA and EVE MCP v1 are not members of any ACCEPTED_BASELINE
```
