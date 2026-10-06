# DESIGN — S1-lite "Verified Delegation Demo v1" — as implemented

```
CLASS     DESIGN RECONSTRUCTION (PROJECT TRACK 052_eva)
STATUS    FROZEN SNAPSHOT
DATE      2026-10-06
BASELINE  1199f223b368b5e871781a4f3032d0be8942c1b4 (main = origin/main, measured 2026-10-06)
```

This document reconstructs the design that was **actually implemented and run**. It does not add,
improve or re-interpret decisions after the fact. Every statement carries its provenance:

```
CODE            present in committed code at 1199f22 (file + sha256 in section 9)
TEST            asserted by committed tests (248 passed with EVA_EVE_CHECKOUT, 228 passed + 20 skipped without)
EVIDENCE        shown in the sealed package evidence/s1lite_live (run index record_sha256 878c1ca9...)
OWNER_DECISION  decided by the owner in the working session; the repository records the result,
                not the decision itself (design rationale, not executed evidence)
```

---

## 1. What S1-lite is

A household delegation demo: the user gives EVA a task and a spending limit; EVA may only book within
the user's confirmed mandate, and only when EVE has verified the evidence and allowed the action.
EVA proposes. EVE decides. The gate enforces.

```
scope            one synthetic service firm, one offer DW-OFFER-001, dishwasher_repair, USD 275     OWNER_DECISION / CODE (data/service_offers_seed.json)
action class     book_service_visit (the only consequential tool of the delegation path)          CODE (dconfig.py)
explanation      exactly one question type: "Why didn't you book it?"                              OWNER_DECISION / CODE (explain.py)
out of scope     real providers, telephony, payments, calendars, execution monitoring, Q6          OWNER_DECISION
proposer (run)   scripted proposer (no LLM); Nova on this flow is NOT established                  OWNER_DECISION / EVIDENCE
```

**Phase boundary.** S1-lite establishes **PRE** (may the action begin?). **DURING** (is it still within
the mandate while it runs?) is **not implemented** and not designed here. **POST** is outside S1-lite.

---

## 2. Frozen boundaries respected

```
EVE core eve-core-v1 tree a698922c...        not modified                                        OWNER_DECISION / EVIDENCE (VPS tree measured before and after)
EVE MCP v1 (vendor/eve-mcp, tree cbdcd191...) not modified                                        OWNER_DECISION
frozen I3A boundary (eva/gate.py, authorization.py, tools.py, data/chain_map.json, eve_client.py)
                                              byte-unchanged; verify_frozen_boundary() == FROZEN   CODE / TEST
eva/web/app.py (supplier demo server)         byte-unchanged                                       OWNER_DECISION (path i) / measured before each D: write
```

---

## 3. Components (all new, package eva_delegation/)

### 3.1 Consequence registry — the mandatory invariant   CODE (consequence_registry.py)

One declaration of which tools can cause an external consequence (`TOOL_CONSEQUENCE`). A gate refuses
to start (`ConsequenceConfigError`) if its tool sets contradict the registry: a consequential tool can
never pass as `NON_CONSEQUENTIAL` because of a configuration mistake. The frozen supplier gate's
configuration is checked against the same registry by tests.   TEST

### 3.2 Mandate and authorization records   CODE (mandate.py)

```
the model may PROPOSE a mandate or an authorization; it never confirms one
EVA reads the proposal back verbatim; only an explicit human confirmation with the exact read-back
  turns it into a sealed record (eva-delegation-mandate-1.0 / eva-delegation-authorization-1.0)
confirmer identity: DECLARED_NOT_AUTHENTICATED
amounts are whole USD integers; floats, bools and strings are refused, never coerced
```

### 3.3 Deterministic within-mandate check   CODE (mandate.check_within_mandate)

Plain code over confirmed records — not the model, not EVE. Basis codes:
`SERVICE_MISMATCH`, `WITHIN_MANDATE_LIMIT`, `EXACT_OFFER_AUTHORIZED`, `QUOTE_EXCEEDS_MANDATE_LIMIT`.

### 3.4 Booking gate — gate path (a)   CODE (gate_booking.py, GATE_VERSION eva-booking-gate-1.0)

A separate, narrow gate for `book_service_visit` only. It reuses the frozen gate's EVE-result
interpretation (`evaluate_eve_result`) by import; the frozen gate is neither modified nor subclassed.
Fail-closed order: `TOOL_NOT_ALLOWED` → non-consequential `PASS` (EVE not called) →
`UNEXPECTED_ARGUMENTS` → `NO_OPERATOR_CHAIN_BINDING` → `PRICE_NOT_IN_EVIDENCE` → EVE error / timeout /
malformed / not evaluated / not allow = `DENY` → otherwise one single-use authorization bound to
(tool_use_id, tool, exact arguments).
OWNER_DECISION: path (a) — no generalisation of the frozen I3A gate.

### 3.5 Tools   CODE (tools.py)

`find_service_offers`, `propose_mandate`, `propose_authorization` (non-consequential) and
`book_service_visit` (consequential; writes a synthetic booking register). The model has **no tool**
that confirms anything.

---

## 4. Evidence construction — D-β and D-α

### 4.1 D-β: declarations built deterministically from confirmed records   CODE (declarations.py) / TEST / EVIDENCE

```
input       confirmed mandate + offer register + (optionally) confirmed authorization; the check is
            RECOMPUTED, no caller-supplied verdict is trusted
timestamps  taken from the records, never from the clock                                           TEST (M3)
documents   raw.documents.sha256 = sha256 of the exact evidence-records file the declaration was built from
approval    approved = true (a confirmed mandate is a human approval on record)
            requested_scope = "book_service_visit DW-OFFER-001 dishwasher_repair USD 275"
            approved_scope  = requested_scope only if within_mandate, else the mandate's own scope
determinism same records -> byte-identical declaration; measured identical on Linux and Windows   EVIDENCE
```

**How this reaches EVE** (measured in the frozen `HumanApprovalAdapter`, eve-core-v1):
`approved_scope != requested_scope` → `APPROVAL_SCOPE_MISMATCH` → policy escalate;
equal scopes → `SUPPORTED`. EVE compares two scope strings; it compares no amounts.

### 4.2 D-α: v2 intake is a visible operator action between processes   CODE (build_declaration.py) / EVIDENCE

The operator CLI writes declaration + evidence-records file with exclusive create, refuses a closed
package (a directory holding `*_RUN_INDEX_*.json`), and validates against eva_intake's own validator
before writing. Intake (print-only, then `--save`) runs on the VPS from
`/opt/eva-demo/eva-intake-dw/`; the binding is a new operator file per version; each version runs in a
new process (D5 B4).

---

## 5. Changes to existing files (the only ones)

```
eva_intake/declaration.py   ACTION_CLASSES += "book_service_visit" (one line)                       CODE (inc 2, ce58fa2)
eva_review/audit.py         binding lookup by per-action-class subject key: subject_of(),
                            SUBJECT_ARG {supplier_id | offer_id}; unknown class -> AuditError        CODE (inc 2)
eva/binding.py   (A)        lock_binding(..., consequential_tools=config.CONSEQUENTIAL_TOOLS);
                            default unchanged; delegation passes dconfig.CONSEQUENTIAL_TOOLS;
                            D5 B4/B5/B7 unchanged                                                  CODE / TEST (inc 3, 0520506); OWNER_DECISION (A)
eva_review/review.py (A')   CONSEQUENTIAL_TOOLS = {set_supplier_risk_status, book_service_visit};
                            unknown tools still skipped; subject check via subject_of
                            (function-level import: audit.py imports review.py); D4 R1-R7 unchanged CODE / TEST (inc 3); OWNER_DECISION (A')
eva/web/static/index.html   delegation mode added, active only when GET /api/mode answers
                            "delegation"; two history/audit display lines tolerate records without
                            a risk level (identical text for supplier records)                     CODE / TEST
```

Both (A) and (A') were found during increment 3 as changes not listed in the design act; the build
stopped and each was owner-approved before it was written to D:.   OWNER_DECISION

---

## 6. Delegation server and explanation

### 6.1 Server — path (i)   CODE (web.py)

`python -m eva_delegation.web` serves the **same** `index.html` in delegation mode; `eva/web/app.py` is
untouched. PolicyObserver sits in front of the booking gate (D5 B12–B13: policy identity observed per
evaluation, mismatch = no action). Binding verified unchanged before every turn (B5). Turn records keep
`record_kind eva_i4_turn` so the existing history and audit machinery reads them. Confirmation route
`POST /api/delegation/confirm` requires the exact pending read-back; the "human channel" means the
model has no tool for it, not that the person is authenticated.   CODE / TEST
OWNER_DECISION: path (i).

### 6.2 "Why didn't you book it?"   CODE (explain.py) / TEST / EVIDENCE

Answer classes `ESTABLISHED`, `NOT_ESTABLISHED`, `OUT_OF_SCOPE`, `SOURCE_VERIFICATION_FAILED`. Every
statement is built from a verified record with its source: the turn (EVE determination), the stored
SAVE intake record (EVE's own gap text) and the mandate record. No causal claim beyond what EVE
recorded; the plain-language sentence "the approval on record does not cover this request" is used
only when EVE's recorded gaps are exactly `APPROVAL_SCOPE_MISMATCH`.

---

## 7. The run (increment 4) — EVIDENCE

```
v1   confirmed mandate USD 200 -> DW-v1 EVA-CH-e1698b4b7d2963f272e1692a (PARTIAL / HUMAN_REVIEW_REQUIRED,
     single gap APPROVAL_SCOPE_MISMATCH) -> "Book the repair." -> EVE escalate EVE-PAR-LOCAL-000035,
     gate DENY, nothing booked -> "Why?" ESTABLISHED
v2   confirmed authorization of DW-OFFER-001 at USD 275 -> DW-v2 EVA-CH-6fb7fe20ec7762db7025c829
     (SUPPORTED, no gaps, supersedes v1) -> new process -> EVE allow EVE-PAR-LOCAL-000036, gate ALLOW,
     booked exactly once
history  000035 ESCALATE / NOT EXECUTED and 000036 ALLOW / EXECUTED side by side; both audits VERIFIED
D-1      unplanned non-consequential turn, cause NOT ESTABLISHED, retained unchanged
```

Authoritative record: `evidence/s1lite_live/S1LITE_RUN_INDEX_2026-10-06.json` (record_sha256
`878c1ca9ba8003493c9b3d93f6c632c4c3abaaccd094718407ff99b0806d04d4`).

---

## 8. Increments

```
1  055f047e8b7e265412da5718d248a7b5fba7e819  core: records, check, booking gate, registry; 46 tests, 8 mutations caught
2  ce58fa26a06582eccfe323f8410bf80372a97b6e  D-beta declarations, D-alpha CLI, intake class, audit subject key; 16 tests, 8 mutations caught
3  0520506aebdc2c727c19a573361b3057ffc14a3d  delegation server, human confirmation, (A), (A'), why; 19 tests, 9 of 10 mutations caught
                                              directly (the 10th is equivalent: caught one layer in by mandate.confirm_*)
4  1199f223b368b5e871781a4f3032d0be8942c1b4  evidence: live run + bindings dishwasher_v1/v2
```

---

## 9. File identities at 1199f22 (sha256, bytes)

```
eva_delegation/__init__.py                    6a3ff5e11c037df2358c244c784737e632db0f128e110b61d468e4efa5b5571b    391
eva_delegation/agent.py                       93da0da5e6f98784fa5bc4e04ae728983dbfd7f9d78c726c261b2f223f44575b   1268
eva_delegation/build_declaration.py           0928aeaa4866fd9659e47681069bd6930a3733e1a26958c0bb44b759ce1809e4   3938
eva_delegation/consequence_registry.py        13697e87ecda57032e112a4128e7ef7ee6963ab2bc65288599f431ee7f0b6c93   1895
eva_delegation/data/service_offers_seed.json  b145a31e7e96b07760d624de27cf2e23309829bf0e08d0a591d230a87827ce64    421
eva_delegation/dconfig.py                     8697eedb65619b30ab908fe65c25f4a828c3ad7be356157cdf4dc8e4e52d9a16    487
eva_delegation/declarations.py                82432456cd048e9ff47d5977f8056a4ab95ba2c0d1fb728da6f207bf98e5f96d   6436
eva_delegation/explain.py                     522d5805c5875ccebd928df370fa31033515d9fdbf4fae31a109e31540143af1   5884
eva_delegation/gate_booking.py                936872a01ad252300329f128ded7c3240e205bf5e3ef20ee4cf930dd54489220   6799
eva_delegation/mandate.py                     0c69cd155c14bf4bd70fc9418690a8e5bf4bfaf03de5d5d6cdc866344a73e2ca   7940
eva_delegation/proposer.py                    12c430457d9c50293c6d85ff555e1d64606ffb5a34e7d9856eebcd74b16ed768   1613
eva_delegation/tools.py                       c0c9fc0f2ba01a098b09ea712404355d7f0caf4e9df472a902b3476fb616e26c   5968
eva_delegation/web.py                         271d656e6f399812d99095744dbd35664757927f458a7cdeb1d726209bd277a2  16901
eva/binding.py                                3f300c70a8993c1a3d41dca51e22ded99752ef3308ce6bc05d94a70a00fd4fbf   6222
eva_review/review.py                          97ee714eb8a034f3c599d23785d82ab661a510ee7a2b0d0d8f5dc2226aef9d2f   8679
eva_review/audit.py                           929009d5e37c292424a83f770e0971d99e2d10cb13d5a27b2db5d51c9aaf2697   8974
eva_intake/declaration.py                     0b7cb4c24137d86ffbf8e24b36f685c1e76e8bf8d3509c142233e53e6276f9b8   8228
eva/web/static/index.html                     48a766532388344c8825740c736afa8ec9a22a10ad4c6db3551678cbb15f28fa  30912
tests/test_delegation_core.py                 8aa1920e24960a869e4d6fa9078e096ee49c02b568789a4763c7efb4a34f7966  14214
tests/test_delegation_declarations.py         738979ed42b281deb6371f1f7d8fdf58794020a14d9e0ba2136d0ab8482ff030  12199
tests/test_delegation_web.py                  b16ad6a4a9c4ad9dd009eae61df4a0931a20c304f7a16b9f97fd8e8675f0d5e3  17311
```

---

## 10. Known limits and non-claims

```
synthetic provider, offer and booking; nothing real is booked or paid
confirmer identity is declared, not authenticated
EVE verifies the declared evidence record; it does not establish that the declared evidence is true
the booking gate's price comes from the offer register (recorded in every turn), not from EVE
Nova on the delegation flow is NOT established
PRE only; DURING not implemented, not designed in this document; POST outside S1-lite
record seals are local, not externally anchored
a browser keeps an old index.html cached after switching servers; a reload without cache is needed
  (observed 2026-10-06; relevant to recording, not to the evidence)
```
