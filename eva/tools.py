"""EVA's tools. The consequential tool refuses to run without a single-use EVE authorization."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from strands import tool

from . import config
from .authorization import AuthorizationError, AuthorizationStore


class SupplierRegister:
    """The demo register the consequential action mutates (a JSON file in a run directory)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, supplier_id: str) -> dict | None:
        return self.load()["suppliers"].get(supplier_id)

    def set_risk_status(self, supplier_id: str, risk_status: str) -> tuple[str, str]:
        data = self.load()
        sup = data["suppliers"][supplier_id]
        old = sup["risk_status"]
        sup["risk_status"] = risk_status
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)
        return old, risk_status


def build_tools(store: AuthorizationStore, register: SupplierRegister, executions: list[dict[str, Any]]):
    @tool
    def get_supplier(supplier_id: str) -> str:
        """Read a supplier's current record (name and risk status) from the supplier register.

        Args:
            supplier_id: The supplier identifier, e.g. SUP-EPSILON-001.
        """
        sup = register.get(supplier_id)
        return json.dumps({"supplier_id": supplier_id, "found": sup is not None, "record": sup})

    @tool(context=True)
    def set_supplier_risk_status(supplier_id: str, risk_status: str, tool_context) -> str:
        """Propose changing a supplier's risk status. The change only happens if EVE allows it.

        Args:
            supplier_id: The supplier identifier, e.g. SUP-EPSILON-001.
            risk_status: One of low, medium, high, critical.
        """
        tool_use_id = str(tool_context.tool_use.get("toolUseId"))
        args = {"supplier_id": supplier_id, "risk_status": risk_status}
        try:
            auth = store.consume(tool_use_id=tool_use_id, tool_name="set_supplier_risk_status", args=args)
        except AuthorizationError as exc:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": str(exc)})
            raise RuntimeError(f"REFUSED: {exc}") from None
        if risk_status not in config.RISK_STATUSES or register.get(supplier_id) is None:
            executions.append({"tool_use_id": tool_use_id, "executed": False, "refusal": "invalid arguments"})
            raise RuntimeError("REFUSED: invalid supplier or risk status")
        old, new = register.set_risk_status(supplier_id, risk_status)
        executions.append({"tool_use_id": tool_use_id, "executed": True, "supplier_id": supplier_id,
                           "old": old, "new": new, "eve_record_id": auth.eve_record_id,
                           "chain_id": auth.chain_id, "nonce": auth.nonce})
        return (f"EXECUTED: {supplier_id} risk_status {old} -> {new}. "
                f"Authorized by EVE record {auth.eve_record_id} (chain {auth.chain_id}).")

    return [get_supplier, set_supplier_risk_status]
