"""Delegation demo tools. No real provider, booking, payment, phone or calendar is ever contacted.

The model may call find_service_offers, propose_mandate and propose_authorization; none of these is
evidence. There is deliberately NO tool that confirms a proposal: confirmation happens only through an
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
from .mandate import MandateError, propose_authorization as _propose_authorization
from .mandate import propose_mandate as _propose_mandate


def load_offers(path: Path = dconfig.DATA_DIR / "service_offers_seed.json") -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "eva-service-offers-1.0":
        raise ValueError("unexpected service offers schema")
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
                executions: list[dict[str, Any]], proposals: list[dict[str, Any]]):

    @tool
    def find_service_offers(service: str) -> str:
        """Find available offers for a household service (synthetic demo data).

        Args:
            service: The service needed, e.g. dishwasher_repair.
        """
        found = {oid: o for oid, o in offers.items() if o["service"] == service}
        return json.dumps({"service": service, "offers": found})

    @tool
    def propose_mandate(service: str, limit_usd: int, window: str) -> str:
        """Propose the user's spending mandate. This is only a proposal: the user must confirm the read-back.

        Args:
            service: The service, e.g. dishwasher_repair.
            limit_usd: The maximum the user allows, in whole US dollars.
            window: When, e.g. "this week".
        """
        try:
            p = _propose_mandate(service=service, limit_usd=limit_usd, window=window)
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
    def book_service_visit(offer_id: str, price_usd: int, tool_context) -> str:
        """Book the visit for one offer at its price. The booking only happens if EVE allows it.

        Args:
            offer_id: The offer to book, e.g. DW-OFFER-001.
            price_usd: The offer's price in whole US dollars.
        """
        tool_use_id = str(tool_context.tool_use.get("toolUseId"))
        args = {"offer_id": offer_id, "price_usd": price_usd}
        try:
            auth = store.consume(tool_use_id=tool_use_id, tool_name="book_service_visit", args=args)
        except AuthorizationError as exc:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": str(exc)})
            raise RuntimeError(f"REFUSED: {exc}") from None
        offer = offers.get(offer_id)
        if offer is None or offer["price_usd"] != price_usd:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": "offer/price mismatch"})
            raise RuntimeError("REFUSED: offer or price does not match the offer register")
        register.book(offer_id, {"provider": offer["provider"], "price_usd": price_usd, "slot": offer["slot"],
                                 "eve_record_id": auth.eve_record_id, "chain_id": auth.chain_id,
                                 "synthetic": True})
        executions.append({"tool_use_id": tool_use_id, "executed": True, "offer_id": offer_id,
                           "price_usd": price_usd, "eve_record_id": auth.eve_record_id,
                           "chain_id": auth.chain_id, "nonce": auth.nonce})
        return (f"BOOKED (synthetic): {offer_id} with {offer['provider']} at ${price_usd}, {offer['slot']}. "
                f"Authorized by EVE record {auth.eve_record_id} (chain {auth.chain_id}).")

    return [find_service_offers, propose_mandate, propose_authorization, book_service_visit]
