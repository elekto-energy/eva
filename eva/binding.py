"""Customer chain binding (decision D5, git blob a23ae05d7520caba7aaf8fbf3bf454f659cabcfa).

Binding selects evidence; it does not establish evidence.

A binding file has exactly the schema eva-chain-map-1.0 and is read with the frozen
eva.gate.load_chain_map(path) (B2). Its identity and SHA-256 are locked when the process starts (B4);
before every turn the file is compared with the locked identity and any difference is a STOP (B5).
Every EVA-CH-* chain in it must be tied to a stored intake record for the same subject and action
class, or the process refuses to start (B7). Without an external binding the frozen chain_map.json
applies exactly as before (B10).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .gate import load_chain_map

FROZEN_CHAIN_MAP = config.DATA_DIR / "chain_map.json"
EVA_CHAIN_PREFIX = "EVA-CH-"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class BindingError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class LockedBinding:
    source: str                     # "external" | "frozen_default"
    path: Path
    sha256: str
    bindings: dict
    intake_records: tuple = field(default_factory=tuple)

    def record(self) -> dict:
        """What every turn record carries (B6)."""
        return {"source": self.source, "file": self.path.name, "sha256": self.sha256,
                "bindings": self.bindings, "intake_records": list(self.intake_records)}

    def verify_unchanged(self) -> None:
        """B5: the file on disk must still be exactly the locked one."""
        try:
            now = hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError as exc:
            raise BindingError("BINDING_UNREADABLE", f"{self.path.name}: {type(exc).__name__}") from None
        if now != self.sha256:
            raise BindingError("BINDING_CHANGED",
                               f"{self.path.name} is {now}, but the process locked {self.sha256}; no reload, no action")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_locked(path: Path, consequential_tools: frozenset = config.CONSEQUENTIAL_TOOLS) -> tuple[str, dict]:
    """Read once, parse with the frozen loader, and refuse if the file changed in between."""
    before = _sha(path)
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
        bindings = load_chain_map(path)                    # the frozen loader (B2)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise BindingError("BINDING_INVALID", f"{path.name}: {type(exc).__name__}: {exc}") from None
    if type(raw) is not dict:
        raise BindingError("BINDING_INVALID", f"{path.name}: not a JSON object")
    if _sha(path) != before or raw.get("bindings") != bindings:
        raise BindingError("BINDING_CHANGED_WHILE_LOCKING", f"{path.name} changed while it was being locked")
    if set(raw) - {"schema", "note", "bindings"}:
        raise BindingError("BINDING_INVALID", f"{path.name}: unknown top-level keys {sorted(set(raw) - {'schema', 'note', 'bindings'})}")
    if type(bindings) is not dict or not bindings:
        raise BindingError("BINDING_INVALID", f"{path.name}: bindings must be a non-empty object")
    for tool, by_subject in bindings.items():
        if tool not in consequential_tools:
            raise BindingError("BINDING_INVALID", f"{path.name}: {tool!r} is not a consequential tool")
        if type(by_subject) is not dict or not by_subject:
            raise BindingError("BINDING_INVALID", f"{path.name}: bindings for {tool!r} must be a non-empty object")
        for subject, chain_id in by_subject.items():
            if not (isinstance(subject, str) and ID_RE.match(subject) and isinstance(chain_id, str) and ID_RE.match(chain_id)):
                raise BindingError("BINDING_INVALID", f"{path.name}: malformed binding {subject!r} -> {chain_id!r}")
    return before, bindings


def _intake_for(chain_id: str, tool: str, subject: str, intakes: list) -> dict:
    """B7: a stored intake record for exactly this chain, subject and action class, or a refusal."""
    for i in intakes:
        b = i.body
        if (b.get("chain", {}).get("chain_id") == chain_id and b.get("mode") == "SAVE"
                and b.get("placement") in ("CREATED", "EXISTS_IDENTICAL")):
            if b.get("action_class") != tool or b.get("subject_ref") != subject:
                raise BindingError("BINDING_SUBJECT_MISMATCH",
                                   f"{chain_id} was taken in for {b.get('action_class')}/{b.get('subject_ref')}, "
                                   f"but is bound for {tool}/{subject}")
            return {"chain_id": chain_id, **i.ref()}
    raise BindingError("BINDING_WITHOUT_INTAKE", f"{chain_id} has no stored intake record among the supplied records")


def lock_binding(path: Optional[Path], intake_dirs: tuple = (),
                 consequential_tools: frozenset = config.CONSEQUENTIAL_TOOLS) -> LockedBinding:
    """Lock the binding for the lifetime of the process (B4)."""
    if path is None:
        sha, bindings = _read_locked(FROZEN_CHAIN_MAP)
        return LockedBinding("frozen_default", FROZEN_CHAIN_MAP, sha, bindings)
    path = Path(path).resolve()
    if not path.is_file():
        raise BindingError("BINDING_MISSING", str(path))
    sha, bindings = _read_locked(path, consequential_tools)
    from eva_review.records import INTAKE_RECORD_GLOB, load_dir      # verified (self-hashed) intake records only
    intakes = [r for d in intake_dirs for r in load_dir(Path(d), INTAKE_RECORD_GLOB, ("eva_chain_intake",))]
    refs = []
    for tool, by_subject in sorted(bindings.items()):
        for subject, chain_id in sorted(by_subject.items()):
            if chain_id.startswith(EVA_CHAIN_PREFIX):
                refs.append(_intake_for(chain_id, tool, subject, intakes))
    return LockedBinding("external", path, sha, bindings, tuple(refs))
