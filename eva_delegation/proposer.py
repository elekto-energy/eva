"""Scripted proposer for the delegation demo (no LLM): a fixed mapping from the demo's utterances to tool calls.

Used for tests and as the no-model option in the delegation page. It only PROPOSES; the booking gate and EVE decide.
"""
from __future__ import annotations

import re

from .tools import load_offers

MANDATE_RE = re.compile(r"up to \$?(\d{1,6})\b", re.I)
APPROVE_RE = re.compile(r"\$?(\d{1,6})\s+is\s+fine\b", re.I)
OFFER_ID = "DW-OFFER-001"


def scripted_turns(utterance: str, tool_use_id: str) -> list[tuple]:
    u = utterance.strip()
    if "repair" in u.lower() and MANDATE_RE.search(u):
        limit = int(MANDATE_RE.search(u).group(1))
        return [("tool", f"{tool_use_id}-offers", "find_service_offers", {"service": "dishwasher_repair"}),
                ("tool", f"{tool_use_id}-mandate", "propose_mandate",
                 {"service": "dishwasher_repair", "limit_usd": limit, "window": "this week"}),
                ("text", "I have proposed your mandate. Please confirm it.")]
    if APPROVE_RE.search(u):
        return [("tool", f"{tool_use_id}-approve", "propose_authorization",
                 {"offer_id": OFFER_ID, "approved_usd": int(APPROVE_RE.search(u).group(1))}),
                ("text", "I have proposed the approval. Please confirm it.")]
    if re.search(r"\bbook\b", u, re.I):
        price = load_offers()[OFFER_ID]["price_usd"]
        return [("tool", f"{tool_use_id}-book", "book_service_visit", {"offer_id": OFFER_ID, "price_usd": price}),
                ("text", "Done.")]
    return [("text", "I can arrange a dishwasher repair within a limit you set.")]
