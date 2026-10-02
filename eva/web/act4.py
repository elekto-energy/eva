"""Act 4 in the web demo: review and audit, as a view over records that already exist.

Nothing here adds review semantics. Every function calls the existing eva_review code (decision D4,
git blob 2869b55c...; decision D5, blob a23ae05d...) and only presents what the verified records say.

UI-1  Absence is visible: NOT_ESTABLISHED values and declared (not established) identities are shown as
      such and never replaced with assumptions.
UI-2  Historical ordering: order and times come from the records themselves (turn_utc, recorded_utc),
      never from load, render or current system time.
UI-3  Verification failure is visible: a missing, changed or unverifiable source record raises; the
      caller shows an explicit failure, never an empty history, a normal state or VERIFIED.

The only write is one review record via eva_review.review.write_review, with the outcomes a human may
choose here limited to DECLINED and HANDLED_BY_HUMAN. NEW_EVIDENCE is explained, not offered: it needs an
operator evidence intake and a new EVE evaluation, which a review cannot supply. No outcome authorises
an action, and nothing here calls EVE, the gate or a tool.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from eva_review import audit as A
from eva_review import review as R
from eva_review.records import INTAKE_RECORD_GLOB, RecordError, load_dir

TURN_GLOB = "TURN_*.json"
REVIEW_GLOB = "REVIEW_*.json"
UI_OUTCOMES = ("DECLINED", "HANDLED_BY_HUMAN")
NEW_EVIDENCE_NOTE = ("New evidence requires a new evidence intake and a new EVE evaluation. "
                     "Human review cannot authorize the action.")
REVIEW_NOTE = "Added after the determination. Does not change it. Authorizes nothing."
VERIFICATION_FAILED = "SOURCE VERIFICATION FAILED. History cannot be established from the current source records."

# Evidence boundaries that hold for every record shown (UI-1). DECLARED_BY_OPERATOR and NOT_ESTABLISHED
# are different statements: the first names the basis of a value, the second says it could not be established.
BOUNDARIES = (
    {"item": "Reviewer identity", "status": "NOT_ESTABLISHED",
     "detail": "the reviewer's name is declared by the reviewer, not authenticated"},
    {"item": "EVE installation identity", "status": "DECLARED_BY_OPERATOR",
     "detail": "declared by the operator, not attested by EVE"},
    {"item": "Truth of the declared evidence", "status": "NOT_ESTABLISHED",
     "detail": "EVE verifies the declared evidence record, not that the declared evidence is true"},
    {"item": "Record seals", "status": "LOCAL",
     "detail": "records are sealed locally, not anchored externally"},
)


class Act4Error(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (RecordError, R.ReviewError, A.AuditError) as exc:
        raise Act4Error(exc.code, exc.detail) from None
    except OSError as exc:
        raise Act4Error("SOURCE_UNREADABLE", type(exc).__name__) from None


def _load(evidence_root: Path, intake_dirs: Iterable[Path]):
    evidence_root = Path(evidence_root)
    turns = load_dir(evidence_root, TURN_GLOB, ("eva_i4_turn",))
    reviews = load_dir(evidence_root / "reviews", REVIEW_GLOB, ("eva_review",))
    intakes = [r for d in intake_dirs for r in load_dir(Path(d), INTAKE_RECORD_GLOB, ("eva_chain_intake",))]
    return turns, reviews, intakes


def _source_paths(evidence_root: Path, intake_dirs: Iterable[Path]) -> dict[str, Path]:
    evidence_root = Path(evidence_root)
    paths = {p.name: p for p in sorted(evidence_root.glob(TURN_GLOB))}
    paths.update({p.name: p for p in sorted((evidence_root / "reviews").glob(REVIEW_GLOB))})
    for d in intake_dirs:
        paths.update({p.name: p for p in sorted(Path(d).glob(INTAKE_RECORD_GLOB))})
    return paths


def _policy_comparison(turn_body: dict, tool_use_id: str):
    obs = [o for o in ((turn_body.get("policy") or {}).get("observations") or []) if o.get("tool_use_id") == tool_use_id]
    if len(obs) != 1:
        return "NOT_ESTABLISHED: the turn record holds no policy observation for this evaluation"
    o = obs[0]
    return {"observed": o.get("observed") or "NOT_ESTABLISHED: EVE reported no policy identity",
            "expected": o.get("expected") or "NOT_ESTABLISHED: no expected identity was locked for the process",
            "result": o.get("result"),
            "source": "turn record, policy.observations (verified by its self-hash)"}


def _history(evidence_root: Path, intake_dirs: Iterable[Path]) -> dict:
    turns, reviews, _ = _load(evidence_root, intake_dirs)
    by_file = {t.file: t for t in turns}
    dets = R.determinations(turns)
    done = R.reviews_by_par(reviews)
    items = []
    for par, d in dets.items():
        t = by_file[d["source"]["file"]].body
        rv = done.get(par)
        binding = t.get("binding")
        items.append({
            "eve_record_id": par,
            "turn_utc": t.get("turn_utc") or "NOT_ESTABLISHED: the turn record has no turn_utc",
            "turn_record": d["source"],
            "request_utterance": t.get("utterance"),
            "args": d["args"],
            "chain_id": d["chain_id"],
            "binding": ({"file": binding.get("file"), "sha256": binding.get("sha256")} if isinstance(binding, dict)
                        else "NOT_ESTABLISHED: the turn record predates binding recording (decision D5)"),
            "verified_chain_outcome": d["verified_chain_outcome"],
            "customer_policy_outcome": d["customer_policy_outcome"],
            "gate_decision": d["gate_decision"],
            "executed": d["executed"],
            "risk_before": (t.get("observed") or {}).get("risk_before"),
            "risk_after": (t.get("observed") or {}).get("risk_after"),
            "requires_review": R.requires_review(d),
            "review": ({"outcome": rv.body["outcome"], "review_id": rv.body["review_id"],
                        "recorded_utc": rv.body["recorded_utc"], "reviewer": rv.body["reviewer"],
                        "note": REVIEW_NOTE} if rv is not None else None),
        })
    # UI-2: ordered by the record's own time; the PAR id only breaks ties
    items.sort(key=lambda i: (str(i["turn_utc"]), i["eve_record_id"]))
    return {"items": items, "boundaries": list(BOUNDARIES), "new_evidence_note": NEW_EVIDENCE_NOTE,
            "order": "by turn_utc recorded in each turn record"}


def history(evidence_root: Path, intake_dirs: Iterable[Path] = ()) -> dict:
    return _wrap(_history, evidence_root, tuple(intake_dirs))


def _queue(evidence_root: Path, intake_dirs: Iterable[Path]) -> list[dict]:
    turns, reviews, _ = _load(evidence_root, intake_dirs)
    return R.queue(turns, reviews)


def review_queue(evidence_root: Path, intake_dirs: Iterable[Path] = ()) -> list[dict]:
    return _wrap(_queue, evidence_root, tuple(intake_dirs))


def _audit(evidence_root: Path, intake_dirs: tuple, eve_record_id: str) -> dict:
    turns, reviews, intakes = _load(evidence_root, intake_dirs)
    bundle = A.export_action(eve_record_id, turns, intakes, reviews)
    # Verify against the bytes on disk *now*, read again after the export was built (UI-3).
    paths = _source_paths(evidence_root, intake_dirs)
    files = {s["file"]: paths[s["file"]].read_bytes() for s in bundle["sources"] if s["file"] in paths}
    A.verify_export(bundle, files)
    turn = next(t for t in turns if t.file == bundle["action"]["turn_record"]["file"])
    return {"verification": "VERIFIED", "export": bundle,
            "policy_comparison": _policy_comparison(turn.body, bundle["proposal"]["tool_use_id"]),
            "register": {"risk_before": (turn.body.get("observed") or {}).get("risk_before"),
                         "risk_after": (turn.body.get("observed") or {}).get("risk_after")},
            "boundaries": list(BOUNDARIES)}


def audit_view(evidence_root: Path, intake_dirs: Iterable[Path], eve_record_id: str) -> dict:
    return _wrap(_audit, evidence_root, tuple(intake_dirs), eve_record_id)


def _submit(evidence_root: Path, intake_dirs: tuple, eve_record_id: str, outcome: str, reviewer: str, note: str) -> dict:
    if outcome not in UI_OUTCOMES:
        raise Act4Error("OUTCOME_NOT_OFFERED", f"{outcome!r} cannot be chosen here; allowed: {UI_OUTCOMES}. {NEW_EVIDENCE_NOTE}")
    turns, reviews, _ = _load(evidence_root, intake_dirs)
    path, body = R.write_review(Path(evidence_root) / "reviews", turns, reviews, eve_record_id=eve_record_id,
                                outcome=outcome, reviewer=reviewer, note=note)
    return {"review_id": body["review_id"], "outcome": body["outcome"], "record": path.name,
            "recorded_utc": body["recorded_utc"], "effects": body["effects"], "note": REVIEW_NOTE}


def submit_review(evidence_root: Path, intake_dirs: Iterable[Path], eve_record_id: str, outcome: str,
                  reviewer: str, note: str = "") -> dict:
    return _wrap(_submit, evidence_root, tuple(intake_dirs), eve_record_id, outcome, reviewer, note)
