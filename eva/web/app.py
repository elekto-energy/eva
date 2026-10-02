"""EVA I4 web server: simulated voice-assistant experience (not Alexa+), localhost only.

  python -m eva.web.app            ->  http://127.0.0.1:8770
  python -m eva.web.app --binding FILE --intakes DIR [--intakes DIR ...] --evidence-dir DIR
                                   ->  same, with an operator chain binding (decision D5)

Each turn runs the same frozen boundary as the CLI: the proposer (scripted, or Amazon Nova when selected)
proposes, EVE decides through the hosted EVE MCP endpoint, the gate enforces, and the register changes
or does not. The spoken report is built from observed state only (eva.web.report). Every turn writes
one self-hashed record to the evidence directory (exclusive create). Secrets are never recorded.
The chain binding is locked when the process starts and recorded in every turn; a changed binding file
is a STOP before any action (D5 B4-B6). The policy identity EVE reports is observed for every
evaluation and recorded as observed; when an expected identity is locked, a mismatch means no action
(D5 B12-B13).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .. import __version__, config
from ..agent import build_agent
from ..authorization import AuthorizationStore
from ..binding import BindingError, LockedBinding, lock_binding
from ..eve_client import EveMcpClient
from ..frozen import FrozenBoundaryError, verify_frozen_boundary
from ..gate import EveGate
from ..policy_identity import PolicyObserver
from . import act4
from ..scripted_model import ScriptedModel
from ..tools import SupplierRegister, build_tools
from .proposer import scripted_turns
from .report import OBSERVED_FIELDS, compose_spoken, observe

HOST = "127.0.0.1"
PORT = 8770
REPO = config.PACKAGE_DIR.parent
STATIC = Path(__file__).parent / "static"
PROPOSERS = ("scripted", "nova")
MAX_UTTERANCE = 300
PAR_RE = re.compile(r"^EVE-PAR-[A-Z]+-[0-9]{1,12}$")
MAX_NOTE = 1000
BUSY_MESSAGE = "EVA is still working on the previous request. Wait for it to finish, then try again."


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _default_nova_factory():
    from ..cli_bedrock import build_nova_model
    return build_nova_model()


def create_app(pre_action: Optional[Callable] = None, nova_factory: Optional[Callable] = None,
               runs_root: Path = REPO / "runs", evidence_root: Path = REPO / "evidence" / "i4",
               binding: Optional[LockedBinding] = None, expected_policy: Optional[dict] = None,
               intake_dirs: tuple = (), review_enabled: bool = False) -> Starlette:
    locked = binding if binding is not None else lock_binding(None)     # D5 B4 / B10
    lock = threading.Lock()
    seq = itertools.count(1)
    state: dict = {}

    def reset_register() -> None:
        d = Path(runs_root) / f"web_{_now()}"
        d.mkdir(parents=True, exist_ok=False)
        p = d / "supplier_register.json"
        shutil.copyfile(config.DATA_DIR / "supplier_register_seed.json", p)
        state["register"] = SupplierRegister(p)

    def snapshot() -> dict:
        return {sid: {"risk_status": rec["risk_status"]} for sid, rec in state["register"].load()["suppliers"].items()}

    class Busy(Exception):
        pass

    def run_turn(utterance: str, proposer: str) -> dict:
        # One turn at a time, and never queued: a Nova call that is being throttled can take minutes,
        # so a second request is refused at once instead of waiting silently behind it.
        if not lock.acquire(blocking=False):
            raise Busy()
        try:
            frozen = verify_frozen_boundary()
            try:
                locked.verify_unchanged()                                # D5 B5: before anything runs
            except BindingError as exc:
                _write_stop(Path(evidence_root), locked, exc)
                raise
            n = next(seq)
            ts = _now()
            tool_use_id = f"eva-web-{ts}-{n}"
            register = state["register"]
            before_sha, before = _sha(register.path), snapshot()
            store, executions = AuthorizationStore(), []
            observer = PolicyObserver(pre_action or EveMcpClient().pre_action, expected_policy)
            gate = EveGate(observer, store, chain_map=locked.bindings)
            proposer_error = None
            model_text = ""
            try:
                model = ScriptedModel(scripted_turns(utterance, tool_use_id)) if proposer == "scripted" \
                    else (nova_factory or _default_nova_factory)()
                agent = build_agent(model, gate, build_tools(store, register, executions))
                model_text = str(agent(utterance)).strip()
            except Exception as exc:  # proposer failure is shown verbatim; never a silent fallback
                proposer_error = f"{type(exc).__name__}: {exc}"[:600]
            after_sha, after = _sha(register.path), snapshot()
            decisions = gate.decisions_as_dicts()
            outcome = observe(decisions, executions, before, after)
            spoken = compose_spoken(outcome)
            if proposer_error:
                spoken = "The proposer failed, so nothing was proposed. Nothing was changed." \
                    if not outcome.proposed else spoken
            turn = {
                "record_kind": "eva_i4_turn", "record_schema_version": "eva-i4-turn-1.1",
                "turn_utc": ts, "turn_seq": n, "eva_version": __version__,
                "proposer": {"kind": proposer,
                             "label": "Scripted proposer (no LLM)" if proposer == "scripted"
                             else f"Amazon Nova ({config.BEDROCK_MODEL_ID}, {config.BEDROCK_REGION})"},
                "proposer_error": proposer_error,
                "utterance": utterance,
                "gate_decisions": decisions,
                "tool_executions": [{k: v for k, v in e.items() if k != "nonce"} for e in executions],
                "authorizations_pending_after": store.pending_count(),
                "register": {"before": before, "after": after, "before_sha256": before_sha,
                             "after_sha256": after_sha, "changed": before_sha != after_sha},
                "observed": {k: getattr(outcome, k) for k in OBSERVED_FIELDS},
                "spoken": spoken,
                "spoken_source": "eva.web.report.compose_spoken(ObservedOutcome) -- observed fields only",
                "model_text": model_text[:2000],
                "frozen_i3a_boundary_verified": frozen,
                "eve": {"policy_ref": config.POLICY_REF, "bearer": "PRESENT_NOT_RECORDED"},
                "binding": locked.record(),
                "policy": {"expected": expected_policy, "observations": observer.observations},
            }
            turn["record_sha256"] = hashlib.sha256(json.dumps(turn, sort_keys=True, separators=(",", ":"),
                                                              ensure_ascii=False).encode("utf-8")).hexdigest()
            ev = Path(evidence_root)
            ev.mkdir(parents=True, exist_ok=True)
            out = ev / f"TURN_{ts}_{n}.json"
            with open(out, "x", encoding="utf-8", newline="\n") as fh:
                json.dump(turn, fh, indent=2, sort_keys=True)
                fh.write("\n")
            turn["evidence_file"] = out.name
            turn["evidence_dir"] = ev.name
            return turn
        finally:
            lock.release()

    async def index(request: Request):
        return FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8")

    async def api_turn(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Send JSON with utterance and proposer."}, status_code=400)
        utterance, proposer = body.get("utterance"), body.get("proposer", "scripted")
        if not isinstance(utterance, str) or not utterance.strip() or len(utterance) > MAX_UTTERANCE:
            return JSONResponse({"error": f"utterance must be 1-{MAX_UTTERANCE} characters."}, status_code=400)
        if proposer not in PROPOSERS:
            return JSONResponse({"error": "proposer must be scripted or nova."}, status_code=400)
        try:
            turn = await run_in_threadpool(run_turn, utterance.strip(), proposer)
        except FrozenBoundaryError as exc:
            return JSONResponse({"error": f"STOP: {exc}"}, status_code=503)
        except BindingError as exc:
            return JSONResponse({"error": f"STOP: {exc.code}: {exc.detail}"}, status_code=503)
        except Busy:
            return JSONResponse({"error": BUSY_MESSAGE}, status_code=409)
        return JSONResponse(turn)

    async def api_register(request: Request):
        return JSONResponse(await run_in_threadpool(snapshot))

    async def api_reset(request: Request):
        def _r():
            if not lock.acquire(blocking=False):
                raise Busy()
            try:
                reset_register()
                return snapshot()
            finally:
                lock.release()
        try:
            return JSONResponse(await run_in_threadpool(_r))
        except Busy:
            return JSONResponse({"error": BUSY_MESSAGE}, status_code=409)

    reset_register()
    # Act 4: review and audit as a view over existing records (eva.web.act4). Reads never call EVE.
    def _read_failure(exc: "act4.Act4Error") -> JSONResponse:
        return JSONResponse({"verification": "FAILED", "error_code": exc.code, "detail": exc.detail,
                             "message": act4.VERIFICATION_FAILED}, status_code=409)

    async def api_history(request: Request):
        try:
            h = await run_in_threadpool(act4.history, Path(evidence_root), intake_dirs)
        except act4.Act4Error as exc:
            return _read_failure(exc)
        return JSONResponse({**h, "review_enabled": review_enabled, "evidence_dir": Path(evidence_root).name})

    async def api_queue(request: Request):
        try:
            return JSONResponse({"items": await run_in_threadpool(act4.review_queue, Path(evidence_root), intake_dirs)})
        except act4.Act4Error as exc:
            return _read_failure(exc)

    async def api_audit(request: Request):
        par = request.path_params["par"]
        if not PAR_RE.match(par):
            return JSONResponse({"error_code": "BAD_PAR", "detail": "not an EVE record id"}, status_code=400)
        try:
            return JSONResponse(await run_in_threadpool(act4.audit_view, Path(evidence_root), intake_dirs, par))
        except act4.Act4Error as exc:
            return _read_failure(exc)

    async def api_review(request: Request):
        if not review_enabled:
            return JSONResponse({"error_code": "REVIEW_DISABLED",
                                 "detail": "Reviews are written only when the demo runs with an explicit --evidence-dir; "
                                           "closed evidence sets are never appended to."}, status_code=403)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error_code": "BAD_REQUEST", "detail": "send JSON"}, status_code=400)
        par, outcome = body.get("eve_record_id"), body.get("outcome")
        reviewer, note = body.get("reviewer"), body.get("note", "")
        if not (isinstance(par, str) and PAR_RE.match(par) and isinstance(outcome, str)
                and isinstance(reviewer, str) and isinstance(note, str) and len(note) <= MAX_NOTE):
            return JSONResponse({"error_code": "BAD_REQUEST", "detail": "eve_record_id, outcome and reviewer are required"},
                                status_code=400)

        def _w():
            if not lock.acquire(blocking=False):
                raise Busy()
            try:
                return act4.submit_review(Path(evidence_root), intake_dirs, par, outcome, reviewer.strip(), note)
            finally:
                lock.release()
        try:
            return JSONResponse(await run_in_threadpool(_w))
        except Busy:
            return JSONResponse({"error": BUSY_MESSAGE}, status_code=409)
        except act4.Act4Error as exc:
            return JSONResponse({"error_code": exc.code, "detail": exc.detail, "message": "Review refused."}, status_code=409)

    app = Starlette(routes=[Route("/", index), Route("/api/turn", api_turn, methods=["POST"]),
                             Route("/api/register", api_register), Route("/api/reset", api_reset, methods=["POST"]),
                             Route("/api/history", api_history), Route("/api/review/queue", api_queue),
                             Route("/api/audit/{par}", api_audit), Route("/api/review", api_review, methods=["POST"])])
    app.state.turn_lock = lock
    return app


def _write_stop(evidence_root: Path, locked: LockedBinding, exc: BindingError) -> None:
    rec = {"record_kind": "eva_i4_turn_stop", "record_schema_version": "eva-i4-turn-stop-1.0",
           "stop_utc": _now(), "stop": {"code": exc.code, "detail": exc.detail},
           "binding_locked": locked.record(), "action": "NONE"}
    rec["record_sha256"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    evidence_root.mkdir(parents=True, exist_ok=True)
    with open(evidence_root / f"STOP_{rec['stop_utc']}.json", "x", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv=None) -> None:
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binding", help="operator chain binding file (eva-chain-map-1.0); default: the frozen chain_map.json")
    ap.add_argument("--intakes", action="append", default=[], help="directory of intake records backing EVA-CH-* bindings")
    ap.add_argument("--evidence-dir", help="where turn records are written (required with --binding)")
    a = ap.parse_args(argv)
    verify_frozen_boundary()
    if a.binding and not a.evidence_dir:
        ap.error("--evidence-dir is required with --binding (closed evidence sets are never appended to)")
    # A closed evidence package must never be used as a writable runtime evidence directory. The run index
    # is the marker of the packages this project closes; finding one is a STOP before anything else runs.
    if a.evidence_dir and any(Path(a.evidence_dir).glob("*_RUN_INDEX_*.json")):
        ap.error(f"{a.evidence_dir} is a closed evidence package (it holds a run index); use a new directory")
    locked = lock_binding(Path(a.binding) if a.binding else None, tuple(a.intakes))
    expected = {"policy_ref": config.POLICY_REF, "policy_content_sha256": config.POLICY_CONTENT_SHA256}
    print(f"binding locked: {locked.source} {locked.path.name} sha256={locked.sha256}")
    print(f"policy locked:  {expected['policy_ref']} {expected['policy_content_sha256']}")
    app = create_app(binding=locked, expected_policy=expected, intake_dirs=tuple(Path(d) for d in a.intakes),
                     review_enabled=bool(a.evidence_dir),
                     evidence_root=Path(a.evidence_dir) if a.evidence_dir else REPO / "evidence" / "i4")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
