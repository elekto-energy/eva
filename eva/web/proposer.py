"""Scripted proposer for the voice demo (no LLM): a fixed keyword reading of the utterance.

It is labelled as scripted everywhere it appears. It only proposes; EVE decides and the gate enforces.
"""
from __future__ import annotations

import re

from .. import config

SUPPLIER_WORDS = {"epsilon": "SUP-EPSILON-001", "zeta": "SUP-ZETA-002"}
NOT_UNDERSTOOD = "I could not tell which supplier and risk level you meant. Try: raise Epsilon to high."


def scripted_turns(utterance: str, tool_use_id: str) -> list[tuple]:
    words = set(re.findall(r"[a-z]+", utterance.lower()))
    suppliers = [sid for w, sid in SUPPLIER_WORDS.items() if w in words]
    levels = [lvl for lvl in config.RISK_STATUSES if lvl in words]
    if len(suppliers) != 1 or len(levels) != 1:
        return [("text", NOT_UNDERSTOOD)]
    return [("tool", tool_use_id, "set_supplier_risk_status",
             {"supplier_id": suppliers[0], "risk_status": levels[0]}),
            ("text", "I asked to update the supplier.")]
