"""Check that every package in package-lock.json comes from the npm registry, with a hash.

    python3 scripts/ci/check_lockfile.py [package-lock.json]

Catches a lockfile edited to fetch from a git URL, a tarball URL or another registry,
and packages locked without a sha512 integrity hash. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REGISTRY = "https://registry.npmjs.org/"


def problems(lock: dict) -> list[str]:
    found = []
    if lock.get("lockfileVersion") != 3:
        found.append(f"lockfileVersion is {lock.get('lockfileVersion')}, expected 3")
    for path, pkg in lock.get("packages", {}).items():
        if not path or pkg.get("link"):
            continue  # the root project, or a workspace link
        resolved, integrity = pkg.get("resolved", ""), pkg.get("integrity", "")
        if not resolved.startswith(REGISTRY):
            found.append(f"{path}: resolved from {resolved or 'nowhere'}")
        if not integrity.startswith("sha512-"):
            found.append(f"{path}: no sha512 integrity hash")
    return found


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0] if argv else "package-lock.json")
    lock = json.loads(path.read_text())
    found = problems(lock)
    for line in found:
        print(line)
    count = len(lock.get("packages", {})) - 1
    print(f"{len(found)} problems in {count} locked packages (all must come from {REGISTRY})")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
