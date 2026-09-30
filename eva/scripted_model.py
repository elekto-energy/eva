"""A deterministic, scripted stand-in for the LLM. Used in Del A (no Bedrock) and in tests.

It proposes exactly the tool calls it is given, then ends with a fixed text. It never reads EVE's
outcome to decide anything; it is a proposer only.
"""
from __future__ import annotations

import json
from typing import Any

from strands.models.model import Model


class ScriptedModel(Model):
    def __init__(self, turns: list[tuple]) -> None:
        # turns: ("tool", tool_use_id, tool_name, input_dict) | ("text", str)
        self.turns = list(turns)
        self.requests: list[Any] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict:
        return {"kind": "scripted"}

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("structured output is not used by EVA")

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.requests.append({"n_messages": len(messages), "tools": [t["name"] for t in (tool_specs or [])]})
        turn = self.turns.pop(0) if self.turns else ("text", "(no further proposal)")
        yield {"messageStart": {"role": "assistant"}}
        if turn[0] == "tool":
            _, tool_use_id, name, inp = turn
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_use_id, "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(inp)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
