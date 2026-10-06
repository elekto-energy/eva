"""Delegation demo configuration (separate from the frozen eva/config.py)."""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
ACTION_CLASS = "book_service_visit"
CONSEQUENTIAL_TOOLS = frozenset({"book_service_visit"})
ALLOWED_TOOLS = frozenset({"find_service_offers", "propose_mandate", "propose_authorization", "book_service_visit"})
BOOKING_ARGS = frozenset({"offer_id", "price_usd"})
SERVICES = ("dishwasher_repair",)
