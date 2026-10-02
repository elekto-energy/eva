"""Observed policy identity per evaluation (decision D5, B12 and B13).

Wraps the pre-action callable given to the frozen gate; the gate itself is unchanged. For every
evaluation it records the policy identity EVE reported (structuredContent.policy.policy_ref and
.policy_content_sha256) exactly as observed. When an expected identity is locked for the process,
any difference -- including a missing identity -- raises, and the gate fails closed: no action.
The observation is never replaced with the expected value and never resolved by a later lookup.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional


class PolicyIdentityMismatch(RuntimeError):
    pass


class PolicyObserver:
    def __init__(self, inner: Callable[[str, dict], Awaitable[dict]], expected: Optional[dict] = None):
        if expected is not None and set(expected) != {"policy_ref", "policy_content_sha256"}:
            raise ValueError("expected policy identity needs exactly policy_ref and policy_content_sha256")
        self._inner = inner
        self.expected = dict(expected) if expected is not None else None
        self.observations: list[dict] = []

    async def __call__(self, chain_id: str, action_context: dict) -> dict:
        raw = await self._inner(chain_id, action_context)
        sc = raw.get("structuredContent") if isinstance(raw, dict) else None
        pol = sc.get("policy") if isinstance(sc, dict) else None
        observed = ({"policy_ref": pol.get("policy_ref"), "policy_content_sha256": pol.get("policy_content_sha256")}
                    if isinstance(pol, dict) else None)
        if self.expected is None:
            result = "NOT_COMPARED"
        else:
            result = "MATCH" if observed == self.expected else "MISMATCH"
        self.observations.append({"chain_id": chain_id, "tool_use_id": (action_context or {}).get("tool_use_id"),
                                  "observed": observed, "expected": self.expected, "result": result})
        if result == "MISMATCH":
            raise PolicyIdentityMismatch(f"observed {observed} != locked {self.expected}")
        return raw
