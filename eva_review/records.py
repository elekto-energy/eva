"""Strict loading of self-hashed EVA records. A record whose self-hash does not verify is refused."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

D4_BLOB = "2869b55c09236ba91d0c23876803a9445b3479ad"
# Intake records are always named INTAKE_<timestamp>_<mode>_<chain>.json (eva_intake.intake); the
# timestamp starts with a digit, so other files in the same directory (e.g. a run index) never match.
INTAKE_RECORD_GLOB = "INTAKE_[0-9]*.json"


class RecordError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Loaded:
    file: str            # file name only (records are referenced by name + hashes, never by machine path)
    file_sha256: str
    body: dict           # the record, including record_sha256

    @property
    def record_sha256(self) -> str:
        return self.body["record_sha256"]

    def ref(self) -> dict:
        return {"file": self.file, "file_sha256": self.file_sha256, "record_sha256": self.record_sha256}


def load_record(path: Path, kinds: tuple[str, ...]) -> Loaded:
    raw = Path(path).read_bytes()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordError("RECORD_UNREADABLE", f"{Path(path).name}: {type(exc).__name__}") from None
    if type(body) is not dict or not isinstance(body.get("record_sha256"), str):
        raise RecordError("RECORD_UNREADABLE", f"{Path(path).name}: not a self-hashed record")
    if body.get("record_kind") not in kinds:
        raise RecordError("WRONG_RECORD_KIND", f"{Path(path).name}: {body.get('record_kind')!r} not in {kinds}")
    rest = {k: v for k, v in body.items() if k != "record_sha256"}
    if canonical_sha256(rest) != body["record_sha256"]:
        raise RecordError("RECORD_TAMPERED", f"{Path(path).name}: self-hash does not verify")
    return Loaded(Path(path).name, hashlib.sha256(raw).hexdigest(), body)


def load_dir(directory: Path, pattern: str, kinds: tuple[str, ...]) -> list[Loaded]:
    if not Path(directory).is_dir():
        return []
    return [load_record(p, kinds) for p in sorted(Path(directory).glob(pattern))]
