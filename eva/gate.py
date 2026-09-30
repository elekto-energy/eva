"""The deterministic EVE gate. Plain Python; no model is consulted.

For every tool call the gate decides, before the tool runs:
  * a tool outside ALLOWED_TOOLS                          -> cancel
  * a non-consequential allowed tool (get_supplier)       -> pass through, EVE not called
  * a consequential tool (set_supplier_risk_status):
      unmapped supplier (no operator chain binding)      -> cancel, EVE not called
      EVE error / timeout / exception / malformed result -> cancel
      anything but pre_action_status == "evaluated" AND
      customer_policy_outcome == "allow" AND a record id
      AND the evaluated chain_id == the bound chain       -> cancel
      otherwise                                           -> mint ONE single-use authorization bound to
                                                             (tool_use_id, tool, exact arguments) and pass
EVE's fields are copied verbatim into the decision; the gate never maps, repairs or translates them.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from . import config
from .authorization import AuthorizationError, AuthorizationStore

PreActionFn = Callable[[str, dict], Awaitable[dict]]

PRE_ACTION_STATUSES = frozenset({"evaluated", "chain_reference_required", "chain_not_found"})
CUSTOMER_POLICY_OUTCOMES = frozenset({"allow", "pause", "escalate", "block",
                                      "policy_not_configured", "no_matching_policy_rule"})


@dataclass
class GateDecision:
    tool_use_id: str
    tool_name: str
    args: dict
    decision: str                      # "ALLOW" | "DENY" | "PASS" (non-consequential)
    reason: str
    chain_id: Optional[str] = None
    eve_called: bool = False
    pre_action_status: Optional[str] = None
    verified_chain_outcome: Optional[str] = None
    customer_policy_outcome: Optional[str] = None
    eve_record_id: Optional[str] = None
    at_utc: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())


def load_chain_map(path: Path = config.DATA_DIR / "chain_map.json") -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "eva-chain-map-1.0":
        raise ValueError("unexpected chain map schema")
    return data["bindings"]


def evaluate_eve_result(raw: Any, expected_chain_id: str) -> tuple[bool, str, dict]:
    """Pure, fail-closed interpretation of an eve_pre_action result. Returns (allowed, reason, fields)."""
    fields: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return False, "MALFORMED: result is not an object", fields
    if raw.get("isError") is not False:
        return False, "EVE_MCP_TOOL_ERROR", fields
    sc = raw.get("structuredContent")
    if not isinstance(sc, dict):
        return False, "MALFORMED: structuredContent missing", fields
    eve = sc.get("eve")
    if not isinstance(eve, dict):
        return False, "MALFORMED: eve envelope missing", fields
    fields = {"pre_action_status": eve.get("pre_action_status"),
              "verified_chain_outcome": eve.get("verified_chain_outcome"),
              "customer_policy_outcome": eve.get("customer_policy_outcome"),
              "eve_record_id": sc.get("eve_record_id"),
              "chain_id": eve.get("chain_id")}
    status, cpo, rid = fields["pre_action_status"], fields["customer_policy_outcome"], fields["eve_record_id"]
    if status not in PRE_ACTION_STATUSES:
        return False, f"MALFORMED: pre_action_status {status!r} outside the closed set", fields
    if status != "evaluated":
        return False, f"NOT_EVALUATED: {status}", fields
    if cpo not in CUSTOMER_POLICY_OUTCOMES:
        return False, f"MALFORMED: customer_policy_outcome {cpo!r} outside the closed set", fields
    if fields["chain_id"] != expected_chain_id:
        return False, "CHAIN_MISMATCH: EVE evaluated a different chain than the operator binding", fields
    if not isinstance(rid, str) or not rid:
        return False, "NO_RECORD: EVE returned no sealed record id", fields
    if cpo != "allow":
        return False, f"EVE_OUTCOME: {cpo}", fields
    return True, "EVE_OUTCOME: allow", fields


class EveGate(HookProvider):
    def __init__(self, pre_action: PreActionFn, store: AuthorizationStore,
                 chain_map: Optional[dict[str, dict[str, str]]] = None,
                 timeout_seconds: float = config.GATE_TIMEOUT_SECONDS, agent_id: str = "eva") -> None:
        self._pre_action = pre_action
        self._store = store
        self._chain_map = chain_map if chain_map is not None else load_chain_map()
        self._timeout = timeout_seconds
        self._agent_id = agent_id
        self.decisions: list[GateDecision] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    async def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool_use = event.tool_use
        tool_use_id = str(tool_use.get("toolUseId"))
        tool_name = str(tool_use.get("name"))
        args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
        try:
            decision = await self._decide(tool_use_id, tool_name, dict(args))
        except Exception as exc:  # the gate never lets an exception through; it fails closed
            decision = GateDecision(tool_use_id, tool_name, dict(args), "DENY",
                                    f"GATE_INTERNAL_ERROR: {type(exc).__name__}")
        self.decisions.append(decision)
        if decision.decision == "DENY":
            event.cancel_tool = self._cancel_message(decision)

    async def _decide(self, tool_use_id: str, tool_name: str, args: dict) -> GateDecision:
        if tool_name not in config.ALLOWED_TOOLS:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "TOOL_NOT_ALLOWED")
        if tool_name not in config.CONSEQUENTIAL_TOOLS:
            return GateDecision(tool_use_id, tool_name, args, "PASS", "NON_CONSEQUENTIAL")
        if set(args) != {"supplier_id", "risk_status"}:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "UNEXPECTED_ARGUMENTS")
        supplier_id = args.get("supplier_id")
        chain_id = self._chain_map.get(tool_name, {}).get(supplier_id) if isinstance(supplier_id, str) else None
        if chain_id is None:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "NO_OPERATOR_CHAIN_BINDING")
        action_context = {"agent_id": self._agent_id, "tool": tool_name, "tool_use_id": tool_use_id,
                          "supplier_id": supplier_id, "requested_risk_status": args.get("risk_status")}
        d = GateDecision(tool_use_id, tool_name, args, "DENY", "", chain_id=chain_id, eve_called=True)
        try:
            raw = await asyncio.wait_for(self._pre_action(chain_id, action_context), timeout=self._timeout)
        except asyncio.TimeoutError:
            d.reason = "EVE_TIMEOUT"
            return d
        except Exception as exc:
            d.reason = f"EVE_UNREACHABLE: {type(exc).__name__}"
            return d
        allowed, reason, f = evaluate_eve_result(raw, chain_id)
        d.reason = reason
        d.pre_action_status = f.get("pre_action_status")
        d.verified_chain_outcome = f.get("verified_chain_outcome")
        d.customer_policy_outcome = f.get("customer_policy_outcome")
        d.eve_record_id = f.get("eve_record_id")
        if allowed:
            try:
                self._store.issue(tool_use_id=tool_use_id, tool_name=tool_name, args=args,
                                  eve_record_id=d.eve_record_id, chain_id=chain_id)
            except AuthorizationError as exc:
                d.reason = f"AUTHORIZATION_REFUSED: {exc}"
                return d
            d.decision = "ALLOW"
        return d

    @staticmethod
    def _cancel_message(d: GateDecision) -> str:
        parts = [f"EVE GATE: action not executed. reason={d.reason}"]
        for k in ("pre_action_status", "verified_chain_outcome", "customer_policy_outcome", "eve_record_id"):
            v = getattr(d, k)
            if v is not None:
                parts.append(f"{k}={v}")
        return " ".join(parts)

    def decisions_as_dicts(self) -> list[dict]:
        return [asdict(d) for d in self.decisions]
