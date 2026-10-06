"""Delegation demo configuration (separate from the frozen eva/config.py)."""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
ACTION_CLASS = "book_service_visit"
CONSEQUENTIAL_TOOLS = frozenset({"book_service_visit"})
ALLOWED_TOOLS = frozenset({"find_household_targets", "find_service_offers", "propose_mandate", "propose_authorization",
                           "book_service_visit"})
# A booking binds the offer, its exact price and the stable identity of the object it concerns.
BOOKING_ARGS = frozenset({"offer_id", "price_usd", "target_id"})
SERVICES = ("dishwasher_repair",)
# The kind of object a service is performed on. Only the stable target_id identifies the object itself.
TARGET_TYPE_FOR_SERVICE = {"dishwasher_repair": "dishwasher"}
