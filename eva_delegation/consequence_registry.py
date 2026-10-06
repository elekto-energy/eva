"""Single declaration of which EVA tools can cause an external consequence.

Invariant (owner rule): a tool that can cause an external consequence must never be able to pass a gate as
NON_CONSEQUENTIAL because of a configuration mistake. Every tool any gate allows must be declared here, and
every tool declared consequential here must be in that gate's consequential set. The booking gate refuses
to start when its configuration contradicts this registry; the frozen supplier gate's configuration is
checked against it by the invariant tests.
"""
from __future__ import annotations

TOOL_CONSEQUENCE: dict[str, bool] = {
    # frozen supplier-risk path (eva/config.py)
    "get_supplier": False,
    "set_supplier_risk_status": True,
    # delegation path (eva_delegation)
    "find_service_offers": False,
    "propose_mandate": False,
    "propose_authorization": False,
    "book_service_visit": True,
}


class ConsequenceConfigError(Exception):
    pass


def check_gate_config(allowed: frozenset[str], consequential: frozenset[str]) -> None:
    """Fail closed if a gate's tool sets contradict the registry. Raises ConsequenceConfigError."""
    if not consequential <= allowed:
        raise ConsequenceConfigError(f"consequential tools not in the allowed set: {sorted(consequential - allowed)}")
    unknown = sorted(t for t in allowed if t not in TOOL_CONSEQUENCE)
    if unknown:
        raise ConsequenceConfigError(f"allowed tools with no consequence declaration: {unknown}")
    leaks = sorted(t for t in allowed if TOOL_CONSEQUENCE[t] and t not in consequential)
    if leaks:
        raise ConsequenceConfigError(f"consequential tools that would pass as NON_CONSEQUENTIAL: {leaks}")
    wrong = sorted(t for t in consequential if not TOOL_CONSEQUENCE[t])
    if wrong:
        raise ConsequenceConfigError(f"tools gated as consequential but declared non-consequential: {wrong}")
