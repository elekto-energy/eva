"""EVA I4 web server: simulated voice-assistant experience (not Alexa+), localhost only.

  python -m eva.web.app            ->  http://127.0.0.1:8770

Each turn runs the same frozen boundary as the CLI: the proposer (scripted, or Amazon Nova when selected)
proposes, EVE decides through the hosted EVE MCP endpoint, the gate enforces, and the register changes
or does not. The spoken report is built from observed state only (eva.web.report). Every turn writes
one self-hashed record to evidence/i4/ (exclusive create). Secrets are never recorded.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
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
from ..eve_client import EveMcpClient
from ..frozen import FrozenBoundaryError, verify_frozen_boundary
from ..gate import EveGate
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
BUSY_MESSAGE = "EVA is still working on the previous request. Wait for it to finish, then try again."


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _default_nova_factory():
    from ..cli_bedrock import build_nova_model
    return build_nova_model()


def create_app(pre_action: Optional[Callable] = None, nova_factory: Optional[Callable] = None,
               runs_root: Path = REPO / "runs", evidence_root: Path = REPO / "evidence" / "i4") -> Starlette:
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
            n = next(seq)
            ts = _now()
            tool_use_id = f"eva-web-{ts}-{n}"
            register = state["register"]
            before_sha, before = _sha(register.path), snapshot()
            store, executions = AuthorizationStore(), []
            gate = EveGate(pre_action or EveMcpClient().pre_action, store)
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
                "record_kind": "eva_i4_turn", "record_schema_version": "eva-i4-turn-1.0",
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
    app = Starlette(routes=[Route("/", index), Route("/api/turn", api_turn, methods=["POST"]),
                             Route("/api/register", api_register), Route("/api/reset", api_reset, methods=["POST"])])
    app.state.turn_lock = lock
    return app


def main() -> None:
    import uvicorn
    verify_frozen_boundary()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
