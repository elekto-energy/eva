"""Per-action audit export (decision D4).

One export per consequential action attempt (one EVE determination, keyed by PAR id). It links
request -> proposal -> evidence/chain -> policy -> EVE determination -> review -> execution/outcome
using only the supplied records, by file name and hashes. A link that the records do not establish is
written as NOT_ESTABLISHED with the reason; nothing is inferred. The determination is always taken
from the turn record itself, so no review can change what the export says EVE decided.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .records import D4_BLOB, Loaded, canonical_sha256
from .review import ReviewError, determinations, requires_review, reviews_by_par


class AuditError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _not_established(reason: str) -> str:
    return f"NOT_ESTABLISHED: {reason}"


def _turn_of(turns: list[Loaded], source: dict) -> Loaded:
    return next(t for t in turns if t.file == source["file"] and t.file_sha256 == source["file_sha256"])


def _chain_lineage(chain_id: str, intakes: list[Loaded]) -> object:
    stored = [i for i in intakes if i.body.get("chain", {}).get("chain_id") == chain_id
              and i.body.get("mode") == "SAVE" and i.body.get("placement") in ("CREATED", "EXISTS_IDENTICAL")]
    if not stored:
        return _not_established("no stored intake record for this chain id among the supplied records")
    first = sorted(stored, key=lambda i: i.body["recorded_utc"])[0]
    b = first.body
    return {"intake_record": first.ref(), "declaration_sha256": b["declaration_sha256"],
            "declared_by": b["declared_by"], "declared_at": b["declared_at"],
            "chain_content_hash": b["chain"]["content_hash"], "supersedes": b.get("supersedes"),
            "eve_tree": b["eve_checkout"]["tree"], "equivalence_gate": b["equivalence_gate"]["status"]}


def export_action(eve_record_id: str, turns: list[Loaded], intakes: list[Loaded],
                  reviews: list[Loaded]) -> dict:
    try:
        dets = determinations(turns)
        done = reviews_by_par(reviews)
    except ReviewError as exc:
        raise AuditError(exc.code, exc.detail) from None
    det = dets.get(eve_record_id)
    if det is None:
        raise AuditError("UNKNOWN_PAR", f"{eve_record_id} is not in the supplied turn records")
    turn = _turn_of(turns, det["source"])
    t = turn.body
    sources = {turn.file: turn.file_sha256}

    review = done.get(eve_record_id)
    if review is not None:
        rb = review.body
        if not requires_review(det):
            raise AuditError("REVIEW_OF_NON_ESCALATE", f"{review.file} reviews {eve_record_id}, which is not an unexecuted escalate")
        if rb["reviewed"]["chain_id"] != det["chain_id"] or rb["reviewed"]["source"] != det["source"]:
            raise AuditError("REVIEW_REFERENCE_MISMATCH", f"{review.file} does not reference this determination exactly")
        sources[review.file] = review.file_sha256
        review_part = {"review_record": review.ref(), "review_id": rb["review_id"], "outcome": rb["outcome"],
                       "reviewer": rb["reviewer"], "recorded_utc": rb["recorded_utc"], "effects": rb["effects"]}
        if rb["outcome"] == "NEW_EVIDENCE":
            ne = rb["new_evidence"]
            successors = [{"eve_record_id": d["eve_record_id"], "customer_policy_outcome": d["customer_policy_outcome"],
                           "gate_decision": d["gate_decision"], "executed": d["executed"], "turn_record": d["source"]}
                          for d in dets.values() if d["chain_id"] == ne["new_chain_id"]]
            review_part["new_evidence"] = {**ne, "later_determinations_on_new_chain":
                                           successors or _not_established("no determination on the new chain among the supplied turn records")}
            for s in successors:
                sources[s["turn_record"]["file"]] = s["turn_record"]["file_sha256"]
            intake_file = ne["intake_record"]["file"]
            match = [i for i in intakes if i.file == intake_file and i.file_sha256 == ne["intake_record"]["file_sha256"]]
            if match:
                sources[intake_file] = match[0].file_sha256
    elif requires_review(det):
        review_part = "NONE_RECORDED"
    else:
        review_part = "NOT_APPLICABLE: the determination did not require human review"

    lineage = _chain_lineage(det["chain_id"], intakes)
    if isinstance(lineage, dict):
        sources[lineage["intake_record"]["file"]] = lineage["intake_record"]["file_sha256"]

    binding = t.get("binding")
    if isinstance(binding, dict):
        bound = (binding.get("bindings") or {}).get(det["tool_name"], {}).get((det["args"] or {}).get("supplier_id"))
        if bound != det["chain_id"]:
            raise AuditError("BINDING_DECISION_MISMATCH",
                             f"the turn's recorded binding gives {bound!r}, but EVE was asked about {det['chain_id']!r}")
        binding_part = {k: binding.get(k) for k in ("source", "file", "sha256", "intake_records")}
    else:
        binding_part = _not_established("the turn record predates binding recording (decision D5)")
    observed = [o for o in ((t.get("policy") or {}).get("observations") or []) if o.get("tool_use_id") == det["tool_use_id"]]
    if len(observed) == 1 and isinstance(observed[0].get("observed"), dict):
        policy_hash = observed[0]["observed"].get("policy_content_sha256") or _not_established("EVE reported no policy hash")
        policy_check = observed[0].get("result")
    else:
        policy_hash = _not_established("not recorded in the turn record")
        policy_check = _not_established("no policy observation for this evaluation")

    executions = [e for e in t.get("tool_executions", []) if e.get("tool_use_id") == det["tool_use_id"]]
    reg = t.get("register") or {}
    bundle = {
        "record_kind": "eva_audit_export", "record_schema_version": "eva-audit-export-1.0",
        "decision_d4_blob": D4_BLOB,
        "action": {"eve_record_id": eve_record_id, "turn_record": turn.ref(), "turn_utc": t.get("turn_utc"),
                   "request_utterance": t.get("utterance"), "proposer": t.get("proposer")},
        "proposal": {"tool_name": det["tool_name"], "args": det["args"], "tool_use_id": det["tool_use_id"]},
        "evidence_chain": {"chain_id": det["chain_id"], "lineage": lineage, "binding": binding_part},
        "policy": {"policy_ref": (t.get("eve") or {}).get("policy_ref") or _not_established("no policy_ref in the turn record"),
                   "policy_content_sha256": policy_hash, "observed_against_locked": policy_check},
        "determination": {k: det[k] for k in ("pre_action_status", "verified_chain_outcome", "customer_policy_outcome",
                                              "gate_decision", "gate_reason")},
        "review": review_part,
        "execution": {"executed_by_eva": det["executed"], "execution_log": executions,
                      "register_before_sha256": reg.get("before_sha256") or _not_established("no register snapshot"),
                      "register_after_sha256": reg.get("after_sha256") or _not_established("no register snapshot"),
                      "register_changed": reg.get("changed") if "changed" in reg else _not_established("no register snapshot")},
        "invariant": "Review may change the future evidence state; it can never change historical truth (D4).",
        "sources": [{"file": f, "sha256": h} for f, h in sorted(sources.items())],
    }
    bundle["export_sha256"] = canonical_sha256(bundle)
    return bundle


def verify_export(bundle: dict, files: dict[str, bytes]) -> None:
    """Raise AuditError unless the export's self-hash and every referenced source file verify."""
    import hashlib
    rest = {k: v for k, v in bundle.items() if k != "export_sha256"}
    if canonical_sha256(rest) != bundle.get("export_sha256"):
        raise AuditError("EXPORT_TAMPERED", "export self-hash does not verify")
    for s in bundle["sources"]:
        data = files.get(s["file"])
        if data is None:
            raise AuditError("SOURCE_MISSING", s["file"])
        if hashlib.sha256(data).hexdigest() != s["sha256"]:
            raise AuditError("SOURCE_CHANGED", f"{s['file']} no longer matches the export")
