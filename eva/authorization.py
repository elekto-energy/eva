"""Single-use authorizations minted by the gate from a successful EVE decision.

An authorization is bound to (tool_use_id, tool_name, exact arguments). The consequential tool
consumes it; replay, a different tool_use_id, a different tool or different arguments all fail.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass


def canonical_args_sha256(args: dict) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Authorization:
    nonce: str
    tool_use_id: str
    tool_name: str
    args_sha256: str
    eve_record_id: str
    chain_id: str


class AuthorizationError(Exception):
    pass


class AuthorizationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, Authorization] = {}
        self._consumed: set[str] = set()

    def issue(self, *, tool_use_id: str, tool_name: str, args: dict, eve_record_id: str, chain_id: str) -> Authorization:
        with self._lock:
            if tool_use_id in self._pending or tool_use_id in self._consumed:
                raise AuthorizationError(f"authorization already issued for tool_use_id {tool_use_id}")
            auth = Authorization(nonce=secrets.token_hex(16), tool_use_id=tool_use_id, tool_name=tool_name,
                                 args_sha256=canonical_args_sha256(args), eve_record_id=eve_record_id,
                                 chain_id=chain_id)
            self._pending[tool_use_id] = auth
            return auth

    def consume(self, *, tool_use_id: str, tool_name: str, args: dict) -> Authorization:
        with self._lock:
            if tool_use_id in self._consumed:
                raise AuthorizationError("authorization already consumed (replay)")
            auth = self._pending.get(tool_use_id)
            if auth is None:
                raise AuthorizationError("no EVE authorization for this tool_use_id")
            if auth.tool_name != tool_name:
                raise AuthorizationError("authorization was issued for a different tool")
            if auth.args_sha256 != canonical_args_sha256(args):
                raise AuthorizationError("arguments differ from the arguments EVE evaluated")
            del self._pending[tool_use_id]
            self._consumed.add(tool_use_id)
            return auth

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
