"""Client for the frozen EVE MCP v1 tool `eve_pre_action` over the authenticated public surface."""
from __future__ import annotations

from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from . import config


class EveMcpClient:
    """Calls eve_pre_action and returns the raw result: {"isError": bool, "structuredContent": dict|None}.

    It interprets nothing; interpretation is the gate's job and is fail-closed there.
    """

    def __init__(self, url: str = config.EVE_MCP_URL, bearer: config.SecretFile | None = None,
                 policy_ref: str = config.POLICY_REF, http_timeout: float = config.GATE_TIMEOUT_SECONDS) -> None:
        self.url = url
        self.bearer = bearer or config.bearer_file()
        self.policy_ref = policy_ref
        self.http_timeout = http_timeout

    async def pre_action(self, chain_id: str, action_context: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.bearer.read()}"}
        async with httpx.AsyncClient(headers=headers, timeout=self.http_timeout) as http:
            async with streamable_http_client(self.url, http_client=http) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.call_tool(config.EVE_TOOL_NAME, {
                        "chain_id": chain_id, "policy_ref": self.policy_ref, "action_context": action_context})
        return {"isError": bool(res.isError), "structuredContent": res.structuredContent}
