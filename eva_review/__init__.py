"""EVA step 6: review queue and audit export, implemented against decision D4
(docs/DECISION_D4_HUMAN_REVIEW_2026-10-02.md, git blob 2869b55c09236ba91d0c23876803a9445b3479ad).

Review may change the future evidence state; it can never change historical truth. Nothing in this
package can execute an action, reach the gate, or turn an EVE escalate into an allow.
"""
