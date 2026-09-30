"""Assembles EVA: a Strands agent whose consequential tool is gated by EVE."""
from __future__ import annotations

from strands import Agent
from strands.tools.executors import SequentialToolExecutor

from . import config
from .gate import EveGate

SYSTEM_PROMPT = (
    "You are EVA, an operations agent. You may propose changes to the supplier register by calling "
    "set_supplier_risk_status. You do not decide whether a change is allowed: an independent EVE "
    "verification decides before the tool runs. If a tool result says the action was not executed, report "
    "that verbatim, including the EVE record id, and do not retry, rephrase or claim the change happened."
)


def build_agent(model, gate: EveGate, tools: list) -> Agent:
    return Agent(model=model, tools=tools, hooks=[gate], system_prompt=SYSTEM_PROMPT,
                 tool_executor=SequentialToolExecutor(), callback_handler=None)


def build_bedrock_model():  # Del B only. Not invoked, not tested live in Del A.
    import boto3
    from strands.models import BedrockModel
    if not (config.BEDROCK_MODEL_ID and config.BEDROCK_REGION and config.BEDROCK_PROFILE):
        raise RuntimeError("model id, region and profile must be pinned explicitly")
    session = boto3.Session(profile_name=config.BEDROCK_PROFILE, region_name=config.BEDROCK_REGION)
    return BedrockModel(boto_session=session, region_name=config.BEDROCK_REGION,
                        model_id=config.BEDROCK_MODEL_ID, streaming=True)
