"""Delegation demo tools. No real provider, booking, payment, phone or calendar is ever contacted.

The model may call find_household_targets, find_service_offers, propose_mandate and propose_authorization;
none of these is evidence. There is deliberately NO tool that confirms a proposal: confirmation happens only through an
explicit human channel outside the model. book_service_visit is the one consequential tool; it refuses to
run without a single-use authorization minted by the booking gate from an EVE allow.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strands import tool

from eva.authorization import AuthorizationError, AuthorizationStore

from . import dconfig
from .mandate import MandateError, describe_target, propose_authorization as _propose_authorization
from .mandate import propose_mandate as _propose_mandate
from .targets import ESTABLISHED, resolve


def load_offers(path: Path = dconfig.DATA_DIR / "service_offers_seed.json") -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "eva-service-offers-1.1":
        raise ValueError("unexpected service offers schema")
    for oid, o in data["offers"].items():
        if not isinstance(o.get("target_id"), str) or not o["target_id"]:
            raise ValueError(f"offer {oid} names no target_id")
    return data["offers"]


class BookingRegister:
    """The synthetic register the consequential action mutates (a JSON file in a run directory)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.exists():
            path.write_text(json.dumps({"schema": "eva-booking-register-1.0", "bookings": {}}, indent=2),
                            encoding="utf-8", newline="\n")

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def book(self, offer_id: str, record: dict) -> None:
        data = self.load()
        if offer_id in data["bookings"]:
            raise RuntimeError(f"{offer_id} is already booked")
        data["bookings"][offer_id] = record
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8", newline="\n")


def build_tools(store: AuthorizationStore, register: BookingRegister, offers: dict[str, dict],
                targets: dict[str, dict], executions: list[dict[str, Any]], proposals: list[dict[str, Any]]):

    @tool
    def find_household_targets(target_type: str) -> str:
        """Find the user's established household objects of one type, e.g. dishwasher. Use only a target_id this
        returns as ESTABLISHED; if it is NOT_ESTABLISHED, ask the user which object they mean - never pick one.

        Args:
            target_type: The kind of object, e.g. dishwasher.
        """
        r = resolve(targets, target_type)
        if r["status"] == ESTABLISHED:
            return json.dumps({"status": ESTABLISHED, "target_id": r["target_id"],
                               "description": describe_target(r["target"])})
        return json.dumps({"status": r["status"], "reason": r["reason"], "candidates": r["candidates"]})

    @tool
    def find_service_offers(service: str) -> str:
        """Find available offers for a household service (synthetic demo data).

        Args:
            service: The service needed, e.g. dishwasher_repair.
        """
        found = {oid: o for oid, o in offers.items() if o["service"] == service}
        return json.dumps({"service": service, "offers": found})

    @tool
    def propose_mandate(target_id: str, service: str, limit_usd: int, window: str) -> str:
        """Propose the user's spending mandate for one established object. This is only a proposal: the user must
        confirm the read-back, which names the object.

        Args:
            target_id: The established object the service is for, e.g. APPLIANCE-001.
            service: The service, e.g. dishwasher_repair.
            limit_usd: The maximum the user allows, in whole US dollars.
            window: When, e.g. "this week".
        """
        target = targets.get(target_id)
        if target is None:
            return f"PROPOSAL REFUSED: {target_id!r} is not an established target"
        try:
            p = _propose_mandate(target=target, service=service, limit_usd=limit_usd, window=window)
        except MandateError as exc:
            return f"PROPOSAL REFUSED: {exc}"
        proposals.append(p)
        return f"PROPOSED (not confirmed): {p['read_back']} The user must confirm before this counts."

    @tool
    def propose_authorization(offer_id: str, approved_usd: int) -> str:
        """Propose that the user approves one exact offer at its exact price. The user must confirm the read-back.

        Args:
            offer_id: The offer, e.g. DW-OFFER-001.
            approved_usd: The exact price the user approves, in whole US dollars.
        """
        offer = offers.get(offer_id)
        if offer is None:
            return f"PROPOSAL REFUSED: unknown offer {offer_id}"
        try:
            p = _propose_authorization(offer=offer, offer_id=offer_id, approved_usd=approved_usd)
        except MandateError as exc:
            return f"PROPOSAL REFUSED: {exc}"
        proposals.append(p)
        return f"PROPOSED (not confirmed): {p['read_back']} The user must confirm before this counts."

    @tool(context=True)
    def book_service_visit(offer_id: str, price_usd: int, target_id: str, tool_context) -> str:
        """Book the visit for one offer, at its price, for the established object it concerns. The booking only
        happens if EVE allows it.

        Args:
            offer_id: The offer to book, e.g. DW-OFFER-001.
            price_usd: The offer's price in whole US dollars.
            target_id: The established object the visit is for, e.g. APPLIANCE-001.
        """
        tool_use_id = str(tool_context.tool_use.get("toolUseId"))
        args = {"offer_id": offer_id, "price_usd": price_usd, "target_id": target_id}
        try:
            auth = store.consume(tool_use_id=tool_use_id, tool_name="book_service_visit", args=args)
        except AuthorizationError as exc:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": str(exc)})
            raise RuntimeError(f"REFUSED: {exc}") from None
        offer = offers.get(offer_id)
        if offer is None or offer["price_usd"] != price_usd or offer["target_id"] != target_id:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": "offer/price/target mismatch"})
            raise RuntimeError("REFUSED: offer, price or target does not match the offer register")
        register.book(offer_id, {"provider": offer["provider"], "price_usd": price_usd, "slot": offer["slot"],
                                 "target_id": target_id,
                                 "eve_record_id": auth.eve_record_id, "chain_id": auth.chain_id,
                                 "synthetic": True})
        executions.append({"tool_use_id": tool_use_id, "executed": True, "offer_id": offer_id,
                           "price_usd": price_usd, "target_id": target_id, "eve_record_id": auth.eve_record_id,
                           "chain_id": auth.chain_id, "nonce": auth.nonce})
        return (f"BOOKED (synthetic): {offer_id} for {target_id} with {offer['provider']} at ${price_usd}, "
                f"{offer['slot']}. "
                f"Authorized by EVE record {auth.eve_record_id} (chain {auth.chain_id}).")

    return [find_household_targets, find_service_offers, propose_mandate, propose_authorization, book_service_visit]
