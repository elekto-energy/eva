"""EVA Verified Delegation demo (S1-lite) web server: simulated voice-assistant experience, not Alexa+, localhost only.

  python -m eva_delegation.web --evidence-dir DIR                                    (mandate session, no binding)
  python -m eva_delegation.web --binding FILE --intakes DIR [--intakes DIR ...] --evidence-dir DIR

Serves the same page as eva.web.app (index.html) in delegation mode; eva/web/app.py is not modified. Each turn:
the proposer (scripted, or Amazon Nova) proposes; proposals (mandate, approval) are only read back -- they become
records ONLY through POST /api/delegation/confirm, a human channel the model has no tool for; a booking goes
through the booking gate, which asks EVE (policy identity observed per evaluation, D5 B12-B13) and lets the
synthetic booking run only on allow. The chain binding is locked at start with the delegation tool set (D5 B4-B7).
Every turn and every confirmation writes one self-hashed record (exclusive create). Secrets are never recorded.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import threading
from pathlib import Path
from typing import Callable, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from eva import __version__, config
from eva.authorization import AuthorizationStore
from eva.binding import BindingError, LockedBinding, lock_binding
from eva.eve_client import EveMcpClient
from eva.frozen import FrozenBoundaryError, verify_frozen_boundary
from eva.policy_identity import PolicyObserver
from eva.scripted_model import ScriptedModel
from eva.web import act4
from eva.web.app import BUSY_MESSAGE, HOST, MAX_UTTERANCE, PAR_RE, PORT, REPO, STATIC, _default_nova_factory, _now

from . import dconfig
from .agent import build_delegation_agent
from .explain import why
from .gate_booking import GATE_VERSION, BookingGate
from .mandate import MandateError, confirm_authorization, confirm_mandate
from .proposer import scripted_turns
from .tools import BookingRegister, build_tools, load_offers

PROPOSERS = ("scripted", "nova")
MAX_NAME = 120
FLOW = "eva-delegation-s1-lite-v1"


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _seal(rec: dict) -> dict:
    rec["record_sha256"] = _sha_bytes(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=False).encode("utf-8"))
    return rec


def _write_record(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")


def compose_spoken(observed: dict, proposals: list[dict]) -> str:
    """Built from observed state only, never from the model's text."""
    if observed["booking_proposed"]:
        if observed["booked"]:
            return (f"EVE allowed the booking. {observed['offer_id']} is booked at ${observed['price_usd']} "
                    f"(synthetic). Evidence record {observed['eve_record_id']}.")
        if observed["customer_policy_outcome"] == "escalate":
            return f"EVE required human review. Nothing was booked. Evidence record {observed['eve_record_id']}."
        return f"The booking was not made. Reason: {observed['gate_reason']}. Nothing was booked."
    if proposals:
        return "Please confirm: " + proposals[-1]["read_back"]
    return "No booking was proposed."


def create_delegation_app(*, evidence_root: Path, pre_action: Optional[Callable] = None,
                          nova_factory: Optional[Callable] = None, runs_root: Path = REPO / "runs",
                          binding: Optional[LockedBinding] = None, expected_policy: Optional[dict] = None,
                          intake_dirs: tuple = ()) -> Starlette:
    offers = load_offers()
    chain_bindings = dict((binding.bindings if binding else {}).get(dconfig.ACTION_CLASS, {}))
    unknown = sorted(set(chain_bindings) - set(offers))
    if unknown:
        raise BindingError("BINDING_INVALID", f"bound offers not in the offer register: {unknown}")
    prices = {oid: offers[oid]["price_usd"] for oid in chain_bindings}
    lock = threading.Lock()
    seq = itertools.count(1)
    state: dict = {"pending": []}
    d = Path(runs_root) / f"delegation_{_now()}"
    d.mkdir(parents=True, exist_ok=False)
    register = BookingRegister(d / "booking_register.json")
    evidence_root = Path(evidence_root)

    class Busy(Exception):
        pass

    def bookings() -> dict:
        return register.load()["bookings"]

    def run_turn(utterance: str, proposer: str) -> dict:
        if not lock.acquire(blocking=False):
            raise Busy()
        try:
            frozen = verify_frozen_boundary()
            if binding is not None:
                binding.verify_unchanged()                                   # D5 B5: before anything runs
            n, ts = next(seq), _now()
            tool_use_id = f"eva-deleg-{ts}-{n}"
            before_sha, before = _sha_bytes(register.path.read_bytes()), bookings()
            store, executions, proposals = AuthorizationStore(), [], []
            observer = PolicyObserver(pre_action or EveMcpClient().pre_action, expected_policy)
            gate = BookingGate(observer, store, chain_bindings=chain_bindings, evidence_prices=prices)
            proposer_error, model_text = None, ""
            try:
                model = ScriptedModel(scripted_turns(utterance, tool_use_id)) if proposer == "scripted" \
                    else (nova_factory or _default_nova_factory)()
                agent = build_delegation_agent(model, gate, build_tools(store, register, offers, executions, proposals))
                model_text = str(agent(utterance)).strip()
            except Exception as exc:                              # shown verbatim; never a silent fallback
                proposer_error = f"{type(exc).__name__}: {exc}"[:600]
            after_sha, after = _sha_bytes(register.path.read_bytes()), bookings()
            decisions = gate.decisions_as_dicts()
            book = [x for x in decisions if x["tool_name"] == dconfig.ACTION_CLASS]
            last = book[-1] if book else {}
            booked = [e for e in executions if e.get("executed")]
            observed = {"booking_proposed": bool(book), "eve_called": bool(last.get("eve_called")),
                        "offer_id": (last.get("args") or {}).get("offer_id"),
                        "price_usd": (last.get("args") or {}).get("price_usd"),
                        "pre_action_status": last.get("pre_action_status"),
                        "customer_policy_outcome": last.get("customer_policy_outcome"),
                        "eve_record_id": last.get("eve_record_id"), "gate_decision": last.get("decision"),
                        "gate_reason": last.get("reason"), "booked": bool(booked),
                        "risk_before": None, "risk_after": None}
            state["pending"] = list(proposals)
            spoken = compose_spoken(observed, proposals)
            if proposer_error and not observed["booking_proposed"] and not proposals:
                spoken = "The proposer failed, so nothing was proposed. Nothing was booked."
            turn = {
                "record_kind": "eva_i4_turn", "record_schema_version": "eva-i4-turn-1.1", "flow": FLOW,
                "turn_utc": ts, "turn_seq": n, "eva_version": __version__, "gate_version": GATE_VERSION,
                "proposer": {"kind": proposer, "label": "Scripted proposer (no LLM)" if proposer == "scripted"
                             else f"Amazon Nova ({config.BEDROCK_MODEL_ID}, {config.BEDROCK_REGION})"},
                "proposer_error": proposer_error, "utterance": utterance, "gate_decisions": decisions,
                "tool_executions": [{k: v for k, v in e.items() if k != "nonce"} for e in executions],
                "authorizations_pending_after": store.pending_count(),
                "proposals": proposals,
                "register": {"before": before, "after": after, "before_sha256": before_sha,
                             "after_sha256": after_sha, "changed": before_sha != after_sha},
                "observed": observed, "spoken": spoken,
                "spoken_source": "eva_delegation.web.compose_spoken(observed, proposals) -- observed fields only",
                "model_text": model_text[:2000], "frozen_i3a_boundary_verified": frozen,
                "eve": {"policy_ref": config.POLICY_REF, "bearer": "PRESENT_NOT_RECORDED"},
                "binding": binding.record() if binding is not None else None,
                "policy": {"expected": expected_policy, "observations": observer.observations},
                "offer_prices_source": {"file": "eva_delegation/data/service_offers_seed.json", "prices": prices},
            }
            _seal(turn)
            out = evidence_root / f"TURN_{ts}_{n}.json"
            _write_record(out, turn)
            turn["evidence_file"], turn["evidence_dir"] = out.name, evidence_root.name
            return turn
        finally:
            lock.release()

    def confirm(kind: str, read_back: str, confirmed_by: str, utterance: str) -> dict:
        if not lock.acquire(blocking=False):
            raise Busy()
        try:
            match = [p for p in state["pending"] if p.get("kind") == f"{kind}_proposal" and p["read_back"] == read_back]
            if not match:
                raise MandateError("no pending proposal with exactly this read-back")
            fn = confirm_mandate if kind == "mandate" else confirm_authorization
            rec = fn(match[-1], confirmed_by=confirmed_by, confirmation_utterance=utterance, read_back_shown=read_back)
            out = evidence_root / f"{kind.upper()}_{_now()}.json"
            _write_record(out, rec)
            state["pending"] = [p for p in state["pending"] if p is not match[-1]]
            return {"record": rec, "file": out.name, "file_sha256": _sha_bytes(out.read_bytes())}
        finally:
            lock.release()

    async def index(request: Request):
        return FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8")

    async def api_mode(request: Request):
        return JSONResponse({"mode": "delegation", "flow": FLOW, "evidence_dir": evidence_root.name,
                             "bound_offers": sorted(chain_bindings),
                             "binding": binding.record() if binding is not None else None})

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
            return JSONResponse(await run_in_threadpool(run_turn, utterance.strip(), proposer))
        except FrozenBoundaryError as exc:
            return JSONResponse({"error": f"STOP: {exc}"}, status_code=503)
        except BindingError as exc:
            return JSONResponse({"error": f"STOP: {exc.code}: {exc.detail}"}, status_code=503)
        except Busy:
            return JSONResponse({"error": BUSY_MESSAGE}, status_code=409)

    async def api_confirm(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "send JSON"}, status_code=400)
        kind, rb, name, utt = (body.get(k) for k in ("kind", "read_back", "confirmed_by", "confirmation_utterance"))
        if kind not in ("mandate", "authorization") or not all(isinstance(x, str) for x in (rb, name, utt)) \
                or len(name) > MAX_NAME or len(utt) > MAX_UTTERANCE:
            return JSONResponse({"error": "kind, read_back, confirmed_by and confirmation_utterance are required"},
                                status_code=400)
        try:
            return JSONResponse(await run_in_threadpool(confirm, kind, rb, name, utt))
        except MandateError as exc:
            return JSONResponse({"error": f"Not confirmed: {exc}"}, status_code=409)
        except Busy:
            return JSONResponse({"error": BUSY_MESSAGE}, status_code=409)

    async def api_state(request: Request):
        def _s():
            return {"pending": state["pending"], "bookings": bookings(),
                    "records": sorted(p.name for p in evidence_root.glob("*.json")
                                      if p.name.startswith(("MANDATE_", "AUTHORIZATION_")))}
        return JSONResponse(await run_in_threadpool(_s))

    async def api_why(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "send JSON with question"}, status_code=400)
        q = body.get("question")
        if not isinstance(q, str) or len(q) > MAX_UTTERANCE:
            return JSONResponse({"error": "question is required"}, status_code=400)
        return JSONResponse(await run_in_threadpool(why, q, evidence_root, intake_dirs))

    def _read_failure(exc: "act4.Act4Error") -> JSONResponse:
        return JSONResponse({"verification": "FAILED", "error_code": exc.code, "detail": exc.detail,
                             "message": act4.VERIFICATION_FAILED}, status_code=409)

    async def api_history(request: Request):
        try:
            h = await run_in_threadpool(act4.history, evidence_root, intake_dirs)
        except act4.Act4Error as exc:
            return _read_failure(exc)
        return JSONResponse({**h, "review_enabled": False, "evidence_dir": evidence_root.name})

    async def api_audit(request: Request):
        par = request.path_params["par"]
        if not PAR_RE.match(par):
            return JSONResponse({"error_code": "BAD_PAR", "detail": "not an EVE record id"}, status_code=400)
        try:
            return JSONResponse(await run_in_threadpool(act4.audit_view, evidence_root, intake_dirs, par))
        except act4.Act4Error as exc:
            return _read_failure(exc)

    async def api_register(request: Request):
        return JSONResponse(await run_in_threadpool(bookings))

    app = Starlette(routes=[Route("/", index), Route("/api/mode", api_mode),
                             Route("/api/delegation/turn", api_turn, methods=["POST"]),
                             Route("/api/delegation/confirm", api_confirm, methods=["POST"]),
                             Route("/api/delegation/state", api_state),
                             Route("/api/delegation/why", api_why, methods=["POST"]),
                             Route("/api/register", api_register), Route("/api/history", api_history),
                             Route("/api/audit/{par}", api_audit)])
    app.state.turn_lock = lock
    return app


def main(argv=None) -> None:
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binding", help="operator chain binding for book_service_visit (eva-chain-map-1.0)")
    ap.add_argument("--intakes", action="append", default=[], help="directory of intake records backing the binding")
    ap.add_argument("--evidence-dir", required=True, help="where turn, mandate and authorization records are written")
    a = ap.parse_args(argv)
    verify_frozen_boundary()
    if any(Path(a.evidence_dir).glob("*_RUN_INDEX_*.json")):
        ap.error(f"{a.evidence_dir} is a closed evidence package (it holds a run index); use a new directory")
    locked = lock_binding(Path(a.binding), tuple(a.intakes), consequential_tools=dconfig.CONSEQUENTIAL_TOOLS) \
        if a.binding else None
    expected = {"policy_ref": config.POLICY_REF, "policy_content_sha256": config.POLICY_CONTENT_SHA256}
    print(f"binding locked: {locked.source} {locked.path.name} sha256={locked.sha256}" if locked
          else "binding: none (mandate session -- every booking is refused before EVE)")
    print(f"policy locked:  {expected['policy_ref']} {expected['policy_content_sha256']}")
    app = create_delegation_app(evidence_root=Path(a.evidence_dir), binding=locked, expected_policy=expected,
                                intake_dirs=tuple(Path(x) for x in a.intakes))
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
