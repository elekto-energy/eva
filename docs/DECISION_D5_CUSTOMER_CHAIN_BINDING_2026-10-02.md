# Decision D5 -- Customer chain binding (2026-10-02)

Status: owner decision, Joakim Eklund, 2026-10-02. Normative architecture decision for EVA.
Step 4 (minimal customer configuration, M1-M4) is implemented against this document, not against any
verbal reading of it. This document contains no implementation.

## Principle

Binding selects evidence; it does not establish evidence.

## Cross-cutting invariant

Nothing that explains a past action is allowed to silently become its present-day replacement.

Concretely, across EVA and EVE:
- evidence is versioned;
- bindings are versioned;
- policies are identified;
- determinations are preserved;
- reviews are appended;
- a turn or action keeps the references that were actually in force when it happened.

## Rules

B1. The chain binding is operator-owned configuration outside the frozen eva/data/chain_map.json. The
    model never sees or chooses a chain id.

B2. A binding file uses exactly the schema eva-chain-map-1.0, is read with the existing frozen
    eva.gate.load_chain_map(path) and is passed to the gate as EveGate(chain_map=...).

B3. Every binding version is an immutable file. Moving from v1 to v2 means a new binding file, never a
    rewrite of an existing one.

B4. Process start. The system reads the binding file, verifies it (B2, B7), computes its SHA-256, and
    locks the file identity and SHA-256 as the binding state of the process. A process has exactly one
    binding state for its whole lifetime; it cannot change or mix bindings.

B5. During the process. Every turn uses exactly the locked binding state. Before each turn the file on
    disk is compared with the locked identity; if it no longer matches, the turn is a STOP: no reload,
    no substitution, no action.

B6. History. Every turn record carries the binding identity and SHA-256 that were locked when the turn
    was created, and the bindings they contained. Later processes, later bindings or later file changes
    never alter that record.

    Operational consequence (not a system property): to use another binding version, the operator
    starts a new process with another immutable binding file.

B7. An EVA-CH-* binding is accepted only if it is tied, fail-closed, to a stored intake record
    (mode SAVE, placement CREATED or EXISTS_IDENTICAL) for the same subject and the same action class.
    Otherwise the process refuses to start.

B8. A binding never establishes that a chain's content is true, approved or sufficient; intake and EVE
    decide that. A binding is not evidence, cannot be cited as evidence, and cannot override decision D4.

B9. The gate continues to verify that EVE answered for exactly the bound chain.

B10. Without an explicit external binding, the frozen eva/data/chain_map.json applies exactly as before.

B11. The five frozen I3A files remain byte-unchanged.

B12. Every turn record states the policy identity that EVE reported for that turn's evaluation
     (policy_ref and policy_content_sha256), observed from EVE's response around the frozen boundary
     without changing it. It is never a later lookup of which policy applies now.

B13. Policy identity mismatch is fail-closed. For every evaluation, the policy identity observed from
     EVE for that evaluation MUST equal the policy identity locked by the operator configuration for the
     process. A mismatch MUST stop the turn before execution. It MUST NOT be treated as a warning,
     substituted with the expected value, or resolved through a later lookup. The turn record records
     the observed value as observed; it is never replaced with the expected value.

## Build scope (step 4)

M1 immutable versioned binding files with the B7 check; M2 web demo integration (binding and turn
evidence directory chosen at start, B4-B6); M3 negative and invariant tests; M4 observed policy
identity per turn (B12, B13).

## Required negative tests

The tests must try to break D5, and each attempt must fail hard:
- a binding to a chain without a stored intake record for the same subject and action;
- an unbound supplier (the gate denies);
- a binding file changed while the process runs (STOP, no action);
- a restart with the v2 binding leaves every earlier turn record byte-identical;
- a binding file cited as evidence (refused by intake and by review);
- no external binding gives exactly the earlier behaviour, and the five frozen files are unchanged;
- the recorded policy identity is the one observed for that evaluation, not a later lookup;
- a policy hash other than the locked one gives no action, and the record keeps the observed value.

## Out of scope

Bindings derived automatically from `supersedes`; multi-customer configuration or tenancy; bindings in
eva/cli.py and eva/cli_bedrock.py; a binding user interface; unfreezing or replacing chain_map.json; a
third evidence version (v3).
