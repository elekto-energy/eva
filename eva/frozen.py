"""The I3A safety boundary, byte-frozen for I3 Del B (owner decision 2026-09-30).

Del B may only add files. These five are the boundary accepted in I3A (closure v2, record ce388636...,
commit c4097185...). Any byte change is a STOP.
"""
from __future__ import annotations

import hashlib

from . import config

FROZEN_I3A_BOUNDARY = {
    "eva/gate.py": "8eeff78772a97508cbf2ee8acfdbbb22c0c4ad08b7677063f3b9e9a58cbc7ed8",
    "eva/authorization.py": "4247e513d5408297e1eecddb6b6b7eb5240a577e17c48d91433b6d8fd087f2ae",
    "eva/tools.py": "70e88f7138ec02f099d0b4e79ebc81909febe63810e99be4a5f68ee0d5e84ac3",
    "eva/data/chain_map.json": "987a7e625d172e797ce1f51cc7f43f7f9cf28e8c63abe53410478ef0b6f94b6c",
    "eva/eve_client.py": "82f6afb2b5685b67bea96ceaa03870367206aec35e2d2d9cc7e4b93d6eeeaa44",
}


class FrozenBoundaryError(RuntimeError):
    pass


def measure_frozen_boundary() -> dict[str, str]:
    repo = config.PACKAGE_DIR.parent
    return {rel: hashlib.sha256((repo / rel).read_bytes()).hexdigest() for rel in FROZEN_I3A_BOUNDARY}


def verify_frozen_boundary() -> dict[str, str]:
    measured = measure_frozen_boundary()
    bad = sorted(rel for rel, h in FROZEN_I3A_BOUNDARY.items() if measured[rel] != h)
    if bad:
        raise FrozenBoundaryError(f"I3A boundary changed: {bad}")
    return measured
