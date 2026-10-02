# Decision D4 -- Human review semantics (2026-10-02)

Status: owner decision, Joakim Eklund, 2026-10-02. Normative architecture decision for EVA.
Step 6 (review queue and audit log) is implemented against this document, not against any verbal
reading of it. This document contains no implementation and no future design.

## Principle

Human review may create new evidence or a new determination, and thereby a new verifiable state.
It must never change earlier evidence, an earlier EVE decision, or a historical action record.

## Rules

R1. An EVE decision (pre-action record, PAR) is bound to one specific chain version and is never
    relabelled. An escalate remains an escalate for that chain version.

R2. EVA executes an action only on an EVE allow for the current chain version, never on a human
    click. A human cannot turn an escalate into an allow through any user interface.

R3. A review has exactly one of three outcomes:
    (a) new evidence: a new declaration, a new intake, a new chain version and a new EVE
        pre-action evaluation. Only an EVE allow for that new chain version lets EVA execute;
    (b) the human declines: recorded, and no action is taken;
    (c) the human performs the action outside EVA: recorded as "handled by human". This records an
        external human action. EVA never executes it, and it does not mean that the original PAR
        decision was approved: the original escalate remains an escalate.

R4. A human approval is expressed as evidence -- in the approval step of a new declaration -- and
    never as an override. EVE then evaluates again.

R5. Review records are append-only and reference the PAR id and the chain id they concern. They
    never modify intake records, probe records, turn records, chains or PARs.

R6. Succession between chain versions is recorded with `supersedes` in the intake records. The
    superseded chain remains in the store unchanged and can be evaluated again.

R7. A review record is never evidence that the action under review was permitted. If a review
    produces new evidence, that evidence receives its own identity (a new declaration and a new
    content-addressed chain) and passes through the intake and EVE flow like any other evidence.

## Empirical basis

The live intake run of 2026-10-02 against eve-core-v1 (tree
a698922c9fd740c4b114e572a626380abf1590a4), committed as evidence in
26c18b6960f804a716465d4021fde14cb27cafb9 (index record
c9a5ba31001a269f673a4985abc84119e70e2821e5bddae987a987bc7f5f41d9), showed:

| Chain | Evidence | EVE outcome | PAR |
|---|---|---|---|
| EVA-CH-e8fcd04353baf54fab0d91d0 (v1) | complete | ACTION_CHAIN_SUPPORTED / allow | EVE-PAR-LOCAL-000021 |
| EVA-CH-995bf4a9f7c53e97719380c9 (v2, supersedes v1) | approval withdrawn | HUMAN_REVIEW_REQUIRED / escalate | EVE-PAR-LOCAL-000022 |
| EVA-CH-e8fcd04353baf54fab0d91d0 (v1, again) | unchanged | ACTION_CHAIN_SUPPORTED / allow | EVE-PAR-LOCAL-000023 |

A change in the evidence produced a new chain version and a new EVE decision; the earlier version
and every earlier PAR remained unchanged (chains 2 -> 4, PAR 20 -> 23, BASELINE_CHECK_PASS). R3(a)
and R4 are the same mechanism in the opposite direction.
