"""Pinned EVA configuration. Nothing here is a secret; secrets are read from files outside the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"

# I3 model candidate, frozen by owner decision 2026-09-30 from measured discovery
# (discovery_round2b.json: AUTHORIZED/AVAILABLE, ON_DEMAND in eu-north-1).
# Invocation capability: NOT_ESTABLISHED until the Del B live invocation gate.
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
BEDROCK_REGION = "eu-north-1"
BEDROCK_PROFILE = "eva-runtime"          # Del B only; never created in Del A

EVE_MCP_URL = "https://grc.eveverified.com/eva/mcp"
EVE_TOOL_NAME = "eve_pre_action"
POLICY_REF = "eve-mcp-demo-policy-v1"
POLICY_CONTENT_SHA256 = "e7a23e8c448ccff96f54ca7a449908e5707a2df5e7f37afcc61d712a285867aa"

GATE_TIMEOUT_SECONDS = 30.0

CONSEQUENTIAL_TOOLS = frozenset({"set_supplier_risk_status"})
ALLOWED_TOOLS = frozenset({"get_supplier", "set_supplier_risk_status"})
RISK_STATUSES = ("low", "medium", "high", "critical")

DEFAULT_BEARER_FILE = r"D:\EVE_SECRETS\eva_mcp_bearer.txt"


@dataclass(frozen=True)
class SecretFile:
    """A secret read from a file outside the repository. Its value is never printed or logged."""
    path: str

    def read(self) -> str:
        p = Path(self.path)
        if not p.is_file():
            raise FileNotFoundError(f"secret file not found: {self.path}")
        value = p.read_text(encoding="ascii").strip()
        if not value:
            raise ValueError(f"secret file is empty: {self.path}")
        return value

    def __repr__(self) -> str:  # never show the value
        return f"SecretFile(path={self.path!r})"


def bearer_file() -> SecretFile:
    return SecretFile(os.environ.get("EVA_MCP_BEARER_FILE", DEFAULT_BEARER_FILE))
