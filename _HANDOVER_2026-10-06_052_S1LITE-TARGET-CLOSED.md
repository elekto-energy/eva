# HANDOVER — PROJECT 052_eva — 2026-10-06 — S1-lite TARGET IDENTITY CLOSED

```
CLASS    NAVIGATION ARTIFACT (PROJECT TRACK)
STATUS   FROZEN SNAPSHOT
DATE     2026-10-06
```

**HANDOFF MAY POINT TO STATE. HANDOFF MUST NOT ASSERT CURRENT STATE.**

Every identity below was measured on 2026-10-06 in the sessions that built, ran and sealed the work it
describes, unless it is labelled OWNER_DECISION, OWNER_REPORTED or NOT_REMEASURED. Measure again before
relying on it. If the disk or a remote differs: STOP and report. This file is immutable; a later state
gets a later dated handover.

Predecessor: `_HANDOVER_2026-10-06_052_S1LITE-CLOSED.md` (sha256
63cf9e2b33df1bf613e7a075ea5137c6aec8ef48376198e3c4091acbf3ff7221, 11256 B, committed in
98d2b96fab806115bf040a17a8fae860798ce063). It describes S1-lite as it stood at 1199f22, before Target
Identity existed. It remains history and is not superseded in content: it is correct for its baseline.

---

## 0. READ THIS FIRST

```
S1-lite / PRE            CLOSED                                         (OWNER_DECISION 2026-10-06)
Target Identity model    IMPLEMENTED + LIVE VERIFIED + SEALED
closing commit           42ec356d6cf2423526614527cda48ad9534bec91
DURING                   NEXT -- NOT STARTED. Not designed, not implemented anywhere in this track.
Atlas                    deliberately outside the 052 track; UNCHANGED  (OWNER_DECISION 2026-09-30, reaffirmed 2026-10-06)
Amazon submission/video  operationally outstanding (PARKED); it does not reopen the architecture
README.md                UNCHANGED in this act
```

---

## 1. THREE BASELINES

```
historical S1-lite        1199f223b368b5e871781a4f3032d0be8942c1b4
                          original S1-lite live run: PAR 000035 / 000036, DW-v1 / DW-v2, evidence/s1lite_live, D-1
                          UNCHANGED (git diff 1199f22..42ec356 -- evidence/s1lite_live bindings/dishwasher_v1.chain_map.json
                          bindings/dishwasher_v2.chain_map.json: empty, measured)

Target Identity code      6d6df5bbbe7c18b4594dd4d73c25ec57144eb3f2
                          strict contract: target_id mandatory in the consequential booking contract

Target Identity evidence  42ec356d6cf2423526614527cda48ad9534bec91
                          sealed live verification: evidence/s1lite_target_live + bindings dishwasher_target_v1/v2
                          + tools/target_negative_control.py. End point of S1-lite.
```

Commits since the predecessor's baseline (each measured from git output in the act that made it):

```
42ec356d6cf2423526614527cda48ad9534bec91  EVA S1-lite: seal target-bound live verification ...      21 files, all A
6d6df5bbbe7c18b4594dd4d73c25ec57144eb3f2  EVA S1-lite: bind delegated repair to established target identity ...  19 files (15 M, 4 A)
98d2b96fab806115bf040a17a8fae860798ce063  Docs: S1-lite design as implemented ... + dated handover ...   2 files
1199f223b368b5e871781a4f3032d0be8942c1b4  (historical baseline)
```

Remote: `https://github.com/elekto-energy/eva.git` (private); `git ls-remote origin refs/heads/main` =
42ec356d6cf2423526614527cda48ad9534bec91 after the evidence push (measured).

---

## 2. THE MODEL (as established by code, tests and the sealed package)

```
USER INTENT
  -> ESTABLISHED TARGET          find_household_targets: exactly one target of the type -> ESTABLISHED; none or several -> NOT_ESTABLISHED (never picks)
  -> EVIDENCE                    sealed target register + sealed coverage facts (describe; never authorize)
  -> CONFIRMED MANDATE           read-back names the object; explicit human confirmation; record binds target_id + target_record_sha256
  -> TARGET-BOUND OFFER          offer register: DW-OFFER-001 concerns APPLIANCE-001
  -> EVE DETERMINATION           declaration scopes carry target_id; EVE compares approved vs requested scope
  -> ENFORCING GATE              booking gate 1.1: TARGET_NOT_IN_EVIDENCE before PRICE_NOT_IN_EVIDENCE before EVE; execution only on allow
  -> OUTCOME                     execution evidence: register before/after in the turn record
  -> WHY                         answer built only from preserved records, each statement with its source
  -> NEW EXPLICIT AUTHORIZATION  exact offer, same target, exact price; human-confirmed
  -> NEW EVIDENCE REVISION       new declaration, new chain, supersedes the previous one; new process (D5 B4)
  -> NEW DETERMINATION
  -> OUTCOME
```

Responsibilities:

```
the model          may propose (target lookup, mandate, approval, booking); it has no tool to confirm
evidence           establishes the target and the facts
the mandate        (and an explicit authorization) gives authority
EVE                makes the determination over the declared evidence
the gate           decides whether the tool may execute; it fails closed
execution evidence establishes what actually happened
why                uses only preserved records
```

---

## 3. TARGET IDENTITY

Principle (OWNER_DECISION, implemented in 6d6df5b):

> **Delegation requires an established target, not merely an action class, when the delegated action
> concerns a specific real-world object.**

```
established target   APPLIANCE-001 (synthetic): dishwasher, Bosch, model SYNTH-DW-100, kitchen
target record        record_sha256 2857fbe5d4243c70a1349e62d992a9d946336e9c8614d868b15dd88802eea1e6
register file        eva_delegation/data/household_targets_seed.json  sha256 06edb56b3a9e734ccf819ffea71713bfb357257cd06c72ea06c62a8d4558e994
                     git blob 71ee78eef2ac9deb4759646c6e07857922baf007
```

Target identity is separate from the action class, the offer, the mandate, the authority and the
descriptive metadata. Only the stable `target_id` is compared; type, manufacturer, model and location
never substitute for it. A re-sealed record with the same id but other metadata is not the record the
mandate was confirmed for and is refused.

Negative control (EVIDENCE: `NEGATIVE_CONTROL_20261006T192644463582Z.json`, record_sha256
c8e9ca2103572fa6838fec79f35a6581b872b533f00c05455bef37279ad13d71, result PASS):

```
APPLIANCE-002 (also a dishwasher)  -> TARGET_NOT_IN_EVIDENCE -> rejected before EVE -> no EVE call -> 0 bookings
"dishwasher" used as an id         -> TARGET_NOT_IN_EVIDENCE -> no EVE call
two dishwashers                    -> NOT_ESTABLISHED / AMBIGUOUS_TARGET (never picks one)
```

Two objects are not equivalent because both are dishwashers.

---

## 4. INPUT IS NOT AUTHORITY

> **Input describes. Mandate authorizes.**

The target register describes the appliance. The coverage evidence describes relevant facts. Neither
creates booking authority. Authority comes only from the explicitly confirmed mandate and, for the
exact offer, the explicitly confirmed authorization.

---

## 5. COVERAGE BOUNDARY

Established by the live evidence (`TARGET_AND_COVERAGE.json`, record_sha256
4dbb8daed40b1e73576b2880958f9d6ab4c6b3639637f0e7c806eaaf4c1f8b32):

```
manufacturer warranty          EXPIRED   (warranty_end 2025-03-14, evaluated at the mandate time 2026-10-06T18:59:04.139423+00:00)
other applicable repair coverage   COVERAGE_NOT_ESTABLISHED
coverage file                  eva_delegation/data/coverage_facts_seed.json  sha256 0c62f87d8354d662989c6ab5d44af6be7caeca3785d911ee84ecc64c1e49e95a
                               git blob 83eef85f31d07fa3abfd5eb5d5469015d331ef3e
```

`COVERAGE_NOT_ESTABLISHED` is NOT `NO_INSURANCE` and NOT `NOT_COVERED`: missing evidence is never
turned into absence, and the code has no such states. Coverage is not an input to the mandate check,
the declaration or the gate; it does not affect booking authority. EXPIRED is stated only from explicit
dates at a record time, never from the clock. No insurance engine and no warranty engine were built.

---

## 6. LIVE RESULTS (EVIDENCE: evidence/s1lite_target_live)

```
proposer      scripted (no LLM). The run does NOT claim that Amazon Nova performed it.
mandate       MANDATE_20261006T185904139423Z.json: APPLIANCE-001, dishwasher repair, this week, up to USD 200;
              confirmed by Joakim Eklund (declared, not authenticated)
Target-v1     EVA-CH-6a454fef0b9a3ea0b799a446 (PARTIAL / HUMAN_REVIEW_REQUIRED, gap APPROVAL_SCOPE_MISMATCH)
              binding bindings/dishwasher_target_v1.chain_map.json sha256 eb63fbc620aa71b6e7d19636fbae5cd20b340da1b20c297b9dfed987607eec3f
PAR 000037    HUMAN_REVIEW_REQUIRED, determination escalate, gate DENY, booking count 0
why           ESTABLISHED: target, USD 200 mandate, USD 275 quote, warranty EXPIRED, other coverage NOT ESTABLISHED,
              EVE's recorded gap; WHY_ANSWER_TARGET_V1.json, recomputed offline from the records present at
              question time and identical
authorization AUTHORIZATION_20261006T190414295015Z.json: DW-OFFER-001 for APPLIANCE-001 at USD 275; human-confirmed
Target-v2     EVA-CH-6233ff2ed6411adea6622030 (SUPPORTED / ACTION_CHAIN_SUPPORTED), supersedes Target-v1 as an
              evidence revision; Target-v1 is neither deleted nor replaced in history
              binding bindings/dishwasher_target_v2.chain_map.json sha256 36388b81ea41cadfb63c00667e05d6174007ffd7079f6caaae8bd0b9a90ae3bd
PAR 000038    ACTION_CHAIN_SUPPORTED, determination allow, gate ALLOW, booking count exactly 1
              (DW-OFFER-001 for APPLIANCE-001, USD 275, synthetic)
both audits   VERIFIED, policy MATCH
unplanned turns   none
```

---

## 7. SEALED PACKAGE

```
directory       evidence/s1lite_target_live/   18 files (17 indexed + the index), all LF
run index       S1LITE_TARGET_RUN_INDEX_2026-10-06.json
  sha256        6b80b2e7e737ac1f511b7919f7204e97ef1fd8c35e3c55b1e8105fb8aa5e41f1   12342 B
  record_sha256 0787b50873c9000cd14b114ae74deaf8dc2b52768afd8de5ae44b3fa6e712d62
  git blob      d5b0036454eaadf42ea58d91648bde9ce4d0b105   (git ls-tree -r 42ec356, measured)
```

Independent verification before commit: all turn self-hashes, mandate and authorization seals, both
D-beta declarations rebuilt byte-identical from the confirmed records, four intake self-hashes, the
negative control's source identities equal to 6d6df5b plus the instrument, the index self-hash and
all 17 indexed file hashes. The package is closed by its run index: the declaration CLI and the
instrument refuse it.

Instrument: `tools/target_negative_control.py` sha256 3278cfe15dda01a50adc7f723d113894f1bdb6a873bc7cfd29f2fcf537613007,
git blob ebe0e449b811ab1cae99493a1b165676effbbe97 (new in 42ec356; local, no network, no PAR).

---

## 8. HOSTED DEMO BACKEND (VPS) — measured 2026-10-06 after the run

```
EVE checkout   /opt/eva-demo/eve-core-v1  tree a698922c9fd740c4b114e572a626380abf1590a4, commit ffe118c326e3d4ec4b194ddea0ba6c8d09d78f27, 0 dirty files
services       eva-eve active, eva-mcp active
EVE MCP code   core.py 07b3acad160d67797166d355b0f88b4a8c25a5a0c4549bb803874c1b8c4242f6,
               server.py c46556f0fb072066de98118785aafc8525ab72d06c7885d0aaad5805900e90d9 -- byte-identical to vendored v1
policy         eve-mcp/policies/policy_registry_v1.json 7d9cd6a72ff48673c58ed0973e228be6a73f87af0d9fb1f03176f3036a39609c;
               locked policy observed per call eve-mcp-demo-policy-v1 e7a23e8c448ccff96f54ca7a449908e5707a2df5e7f37afcc61d712a285867aa
intake code    /opt/eva-demo/eva-intake-dw/eva_intake/declaration.py 0b7cb4c24137d86ffbf8e24b36f685c1e76e8bf8d3509c142233e53e6276f9b8 (unchanged)
store before   chains.json 9a4d2aaa38f8f023b5191a2acbe17ad72d572978b55902d6716c0b9baceee181  6 chains
               pre_action_records.json c9eac484687d29d99501c6ed8e72f999392b04e62d62bfe2d602f89805f1c73a  36 records
store after    chains.json 90aff696c4e2fee759c4dc6db9bfedc33b10a5f61834a65fa0c0b625e8486570  76676 B  8 chains
               pre_action_records.json cc9c496de88f3f2308d94994bf93bb1d866cd012bfbce00d61038b10cecbd87e  145556 B  38 records
delta          exactly 2 new chains and exactly 2 new PAR records (000037, 000038); nothing else changed
added          /opt/eva-demo/incoming/dw_target, /opt/eva-demo/evidence/dw_target_intake
historical PAR 000035 escalate (EVA-CH-e1698b4b7d2963f272e1692a), 000036 allow (EVA-CH-6fb7fe20ec7762db7025c829) -- present, unchanged
public surface https://grc.eveverified.com/eva/mcp (bearer); must stay up through judging (OWNER_DECISION)
```

---

## 9. PRESERVED HISTORY

```
evidence/s1lite_live/            unchanged; run index sha256 42685cb25e9d30c6998caecd28c541e7ff63fc5e5a24ee1bd6574997fb4cb8d6,
                                 record_sha256 878c1ca9ba8003493c9b3d93f6c632c4c3abaaccd094718407ff99b0806d04d4 (self-hash verified)
bindings/dishwasher_v1.chain_map.json   unchanged  88d65161824c9c394526d3ab114284948301f00f6448d22c2fbb372e182830a7
bindings/dishwasher_v2.chain_map.json   unchanged  f0593d25c94ef9cdadba6384f7aba63cff31488517200cd760624319aa449898
PAR 000035 / 000036              historical facts on the VPS store, unchanged
D-1                              preserved in the historical package
```

Target Identity did not rewrite previous evidence; it added new chains, records and a new package.

> **Evidence can change; history cannot.**

---

## 10. FROZEN / UNCHANGED BOUNDARIES

Not changed by the Target Identity work (6d6df5b, 42ec356): EVE core, EVE MCP v1, EVE policy, the
frozen I3A boundary (verified by test), `eva/`, `eva_review/`, `eva_intake/`, `vendor/`,
`eva/web/app.py`, the supplier demo, Atlas, Q6, POST, DURING.

Not built: a generic asset manager, insurance engine, warranty engine, household graph, OCR/vision
system, external repair marketplace, or a real booking/payment system.

Regression at 6d6df5b on the workstation: 270 passed with `EVA_EVE_CHECKOUT=D:\EVE_DEMO\eve-core-v1`;
248 passed, 22 skipped without; supplier and all non-S1-lite tests 167 passed; target matrix 18 passed;
12/12 mutations caught. Re-run after the live act with the package present: 270 / 248 + 22.

---

## 11. OWNER DECISIONS RECORDED IN THIS PHASE (2026-10-06)

```
Target Identity act: Phase A read-only measurement, then GO for the measured minimum change set
H1  target_id mandatory; existing S1-lite tests updated to the strict contract; no optional/backward-compatible
    target path; historical reproducibility anchored at 1199f22
H3  _HANDOVER_CURRENT.md left untouched until this closing act
live verification GO: new target-bound chains and bindings with distinct names; historical DW-v1/v2 untouched
commit GOs for 6d6df5b (19 files) and 42ec356 (21 files); explicit staging by path; the pointer never staged with them
this act: final handover + pointer; documentation only
```

---

## 12. DEVIATIONS, RECORDED — NOT CORRECTED

```
PHASE7_DEFAULT       the FRÅGESTOPP on the negative-control method was not answered; the stated default
                     (instrument tools/target_negative_control.py) was applied and is recorded in the run index
WHY_CAPTURE          the server writes no record for "why"; the answer was preserved by re-querying the same
                     read-only endpoint and was recomputed offline from the records present at question time (identical)
VERIFIER_ASSUMPTION  a producer verification script first assumed a register field name; it was measured and the
                     check re-run; no evidence was affected
COMMIT_ORDER_42EC356 the evidence commit was made before the producer had confirmed the staged blobs; all 21 blobs
                     were verified against the commit (git ls-tree) before push; content unaffected
```

---

## 13. NEXT ARCHITECTURAL WORK

```
DURING   NEXT -- NOT STARTED
```

PRE is established through S1-lite. The candidate `OBSERVE -> BIND -> RE-EVALUATE -> CONTINUE / STOP / ESCALATE`
is a design hypothesis only, until separate GRC read-only/design work establishes the contract. Existing
Q6 and POST work is separate and must be reconstructed from its own authoritative artifacts before
DURING is designed. No DURING implementation exists in this track.

Atlas was intentionally outside Project 052 / S1-lite and was not mutated. Any future representation of
Verified Delegation PRE/DURING/POST in Atlas requires a separate owner decision.

---

## 14. OPEN ITEMS (not started unless stated)

```
Amazon submission    PARKED: video, README, testing instructions, judge token, submission text, friction log,
                     product-feedback questions, repository sharing at submission
docs/DESIGN_S1LITE_VERIFIED_DELEGATION_2026-10-06.md   describes S1-lite at 1199f22 (before Target Identity);
                     not updated in this act
eva/web/static/index.html   unchanged; target and coverage appear in read-backs, turn records and why, not as
                     dedicated UI fields
naming               the synthetic target names a real manufacturer (Bosch); model and dates are synthetic.
                     Changing it would require a new target record, new chains and a new run
Nova on S1-lite      not run; optional, separately labelled
AWS                  items as recorded in the predecessor (NOT_REMEASURED here)
```

---

## 15. NON-CLAIMS

```
this handover asserts no current state; it points at state measured on 2026-10-06
no DURING or POST capability exists in this track
Nova has not performed S1-lite or the Target Identity run
the target, offer, provider, warranty dates and booking are synthetic; nothing real is booked or paid
confirmer identity is declared, not authenticated
EVE verifies the declared evidence; it does not establish that the declared evidence is true
EVE installation identity on the VPS remains OPERATOR_DECLARED
EVA and EVE MCP v1 are not members of any ACCEPTED_BASELINE
```
