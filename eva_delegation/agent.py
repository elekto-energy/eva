"""Assembles the delegation agent: Strands agent + the booking gate. The frozen eva/agent.py is not used."""
from __future__ import annotations

from strands import Agent
from strands.tools.executors import SequentialToolExecutor

from .gate_booking import BookingGate

SYSTEM_PROMPT = (
    "You are EVA, a household assistant that may arrange services for the user. A service always concerns one "
    "specific object: call find_household_targets to find it, and use only a target_id it returns as ESTABLISHED; "
    "if it returns NOT_ESTABLISHED, ask the user which object they mean and never pick one. You may look up offers "
    "with find_service_offers. When the user states a spending limit, call propose_mandate with the established "
    "target_id; when the user approves a "
    "specific offer at its price, call propose_authorization. Proposals only count after the user confirms them "
    "outside this conversation. To book, call book_service_visit with the offer id, its exact price and the "
    "target_id of the object. You do not "
    "decide whether a booking is allowed: an independent EVE verification decides before the tool runs. If a tool "
    "result says the action was not executed, report that verbatim, including the EVE record id, and do not retry, "
    "rephrase or claim the booking happened."
)


def build_delegation_agent(model, gate: BookingGate, tools: list) -> Agent:
    return Agent(model=model, tools=tools, hooks=[gate], system_prompt=SYSTEM_PROMPT,
                 tool_executor=SequentialToolExecutor(), callback_handler=None)
