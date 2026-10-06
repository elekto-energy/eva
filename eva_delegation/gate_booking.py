"""Booking gate (gate path a): a separate, narrow, versioned gate for book_service_visit only.

It reuses the frozen I3A gate's EVE-result interpretation (evaluate_eve_result) and decision type by IMPORT;
the frozen gate itself is not modified and not subclassed. Decision order, all fail-closed:

  * a tool outside the delegation ALLOWED_TOOLS                      -> DENY TOOL_NOT_ALLOWED
  * a non-consequential allowed tool                                 -> PASS, EVE not called
  * book_service_visit:
      arguments other than exactly {offer_id, price_usd}             -> DENY UNEXPECTED_ARGUMENTS
      offer_id with no operator chain binding                        -> DENY NO_OPERATOR_CHAIN_BINDING
      price_usd different from the price in the bound evidence       -> DENY PRICE_NOT_IN_EVIDENCE
      EVE error / timeout / malformed / not evaluated / not allow    -> DENY (EVE fields copied verbatim)
      otherwise                                                      -> ONE single-use authorization bound to
                                                                        (tool_use_id, tool, exact arguments)
Construction fails closed (ConsequenceConfigError) if the tool sets contradict consequence_registry.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Optional

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from eva import config as eva_config
from eva.authorization import AuthorizationError, AuthorizationStore
from eva.gate import GateDecision, PreActionFn, evaluate_eve_result

from . import dconfig
from .consequence_registry import check_gate_config

GATE_VERSION = "eva-booking-gate-1.0"


class BookingGate(HookProvider):
    def __init__(self, pre_action: PreActionFn, store: AuthorizationStore, *,
                 chain_bindings: dict[str, str], evidence_prices: dict[str, int],
                 allowed_tools: frozenset[str] = dconfig.ALLOWED_TOOLS,
                 consequential_tools: frozenset[str] = dconfig.CONSEQUENTIAL_TOOLS,
                 timeout_seconds: float = eva_config.GATE_TIMEOUT_SECONDS, agent_id: str = "eva") -> None:
        check_gate_config(allowed_tools, consequential_tools)        # refuse to start on a leaking config
        if set(chain_bindings) != set(evidence_prices):
            raise ValueError("every bound offer needs exactly one evidence price, and vice versa")
        for oid, price in evidence_prices.items():
            if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
                raise ValueError(f"evidence price for {oid} must be a positive whole-dollar int")
        self._pre_action = pre_action
        self._store = store
        self._bindings = dict(chain_bindings)
        self._prices = dict(evidence_prices)
        self._allowed = allowed_tools
        self._consequential = consequential_tools
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
        except Exception as exc:  # never let an exception through; fail closed
            decision = GateDecision(tool_use_id, tool_name, dict(args), "DENY",
                                    f"GATE_INTERNAL_ERROR: {type(exc).__name__}")
        self.decisions.append(decision)
        if decision.decision == "DENY":
            event.cancel_tool = self._cancel_message(decision)

    async def _decide(self, tool_use_id: str, tool_name: str, args: dict) -> GateDecision:
        if tool_name not in self._allowed:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "TOOL_NOT_ALLOWED")
        if tool_name not in self._consequential:
            return GateDecision(tool_use_id, tool_name, args, "PASS", "NON_CONSEQUENTIAL")
        if set(args) != dconfig.BOOKING_ARGS:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "UNEXPECTED_ARGUMENTS")
        offer_id, price = args.get("offer_id"), args.get("price_usd")
        chain_id = self._bindings.get(offer_id) if isinstance(offer_id, str) else None
        if chain_id is None:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "NO_OPERATOR_CHAIN_BINDING")
        if isinstance(price, bool) or not isinstance(price, int) or price != self._prices[offer_id]:
            return GateDecision(tool_use_id, tool_name, args, "DENY", "PRICE_NOT_IN_EVIDENCE", chain_id=chain_id)
        action_context = {"agent_id": self._agent_id, "tool": tool_name, "tool_use_id": tool_use_id,
                          "offer_id": offer_id, "price_usd": price, "gate": GATE_VERSION}
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
