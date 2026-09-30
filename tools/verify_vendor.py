"""verify_vendor.py -- prove that vendor/eve-mcp is byte-for-byte the frozen EVE MCP v1.

EVE MCP v1 is an immutable dependency of EVA. Its identity is the Git TREE of tag
eve-mcp-v1 (commit shas depend on author/time; the tree does not). This tool needs
no git: it recomputes the tree id from the vendored bytes with the Git object
model, checks the freeze manifest's self-hash against the pinned value, and checks
every inventoried file against the manifest's SHA-256.

Exit 0 only when everything matches. No fallback, no partial pass.

Usage:  python tools/verify_vendor.py [--vendor vendor/eve-mcp]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

PINNED_TAG = "eve-mcp-v1"
PINNED_TREE = "cbdcd191710c472f7706a9487f31eef3cfd1821d"           # git tree of eve-mcp-v1
PINNED_COMMIT = "a0a5fe34a5498390d728f5f0923308e1731186b4"         # informational only
PINNED_MANIFEST_RECORD_SHA256 = "dfedb266ad1bb7a3e7af257eb9dd761445efe328a66dee46cb2a1b74ff18128d"
PINNED_MANIFEST_FILE = "FREEZE_MANIFEST_EVE_MCP_v1.json"
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "eve_mcp.egg-info"}
IGNORED_FILES = set()


def _blob_id(data: bytes) -> bytes:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).digest()


def _tree_id(directory: str) -> bytes:
    """Git tree object id of a directory (files 100644, dirs 40000; git sort order)."""
    entries = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            if name in IGNORED_DIRS:
                continue
            entries.append((name + "/", b"40000 " + name.encode() + b"\0" + _tree_id(path)))
        elif os.path.isfile(path):
            if name in IGNORED_FILES:
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            entries.append((name, b"100644 " + name.encode() + b"\0" + _blob_id(data)))
    entries.sort(key=lambda e: e[0].encode())
    body = b"".join(e[1] for e in entries)
    return hashlib.sha1(b"tree %d\0" % len(body) + body).digest()


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vendor", default=os.path.join("vendor", "eve-mcp"))
    a = ap.parse_args(argv)
    vendor = os.path.abspath(a.vendor)
    failures = []

    if not os.path.isdir(vendor):
        print(f"FAIL vendor directory missing: {vendor}")
        return 2

    # 1. tree identity (the authoritative check)
    tree = _tree_id(vendor).hex()
    print(f"tree     {tree}  expected {PINNED_TREE}  {'MATCH' if tree == PINNED_TREE else 'MISMATCH'}")
    if tree != PINNED_TREE:
        failures.append("tree")

    # 2. manifest self-hash against the pinned record hash
    mpath = os.path.join(vendor, PINNED_MANIFEST_FILE)
    try:
        with open(mpath, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
        claimed = manifest.pop("record_sha256")
        recomputed = canonical_sha256(manifest)
        ok = claimed == recomputed == PINNED_MANIFEST_RECORD_SHA256
        print(f"manifest record_sha256 claimed={claimed[:16]}... recomputed={recomputed[:16]}... "
              f"pinned={PINNED_MANIFEST_RECORD_SHA256[:16]}...  {'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            failures.append("manifest")
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL manifest unreadable: {exc}")
        failures.append("manifest")
        manifest = {"file_inventory": {}}

    # 3. every inventoried file byte-exact
    inv = manifest.get("file_inventory", {})
    bad = 0
    for rel, meta in sorted(inv.items()):
        p = os.path.join(vendor, *rel.split("/"))
        try:
            with open(p, "rb") as fh:
                data = fh.read()
            got = hashlib.sha256(data).hexdigest()
            status = "ok" if (got == meta["sha256"] and len(data) == meta["bytes"]) else "MISMATCH"
        except OSError:
            status = "MISSING"
        if status != "ok":
            bad += 1
        print(f"  {status:8s} {rel}")
    print(f"inventory {len(inv) - bad}/{len(inv)} files match")
    if bad:
        failures.append("inventory")

    # 4. report files present but outside the hashed inventory (expected: manifest + pointer)
    present = set()
    for root, dirs, files in os.walk(vendor):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            present.add(os.path.relpath(os.path.join(root, f), vendor).replace(os.sep, "/"))
    extra = sorted(present - set(inv))
    print(f"outside inventory (covered by the tree check): {extra}")

    if failures:
        print(f"VENDOR_VERIFY FAIL {failures}")
        return 1
    print(f"VENDOR_VERIFY PASS  vendor/eve-mcp == {PINNED_TAG} tree {PINNED_TREE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
