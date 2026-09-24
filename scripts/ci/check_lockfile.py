"""Check that every package in package-lock.json is the registry's own tarball for it, with a hash.

    python3 scripts/ci/check_lockfile.py [package-lock.json]

Runs before `npm ci`, so nothing is downloaded from a bad lockfile. Catches a lockfile
edited to fetch from a git URL, a tarball URL or another registry; one that swaps a package
for a different registry package (with that package's real hash), which `npm audit
signatures` can't see, whether by renaming an entry, a link or an odd path; and packages
locked without a sha512 integrity hash. Reads package.json from the lockfile's folder.
Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REGISTRY = "https://registry.npmjs.org/"
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
NAME = r"(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*"
# node_modules/<name>, nested any number of times; no ".", ".." or empty segments.
PATH_KEY = re.compile(rf"node_modules/{NAME}(?:/node_modules/{NAME})*")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
# Aliases ("<folder>": "npm:<package>@<range>") that a dependency declares, as (folder,
# package) pairs a person has checked. npm ci doesn't compare a lockfile entry's name with
# what was asked for, so an alias package.json doesn't declare could be an edit that swaps a
# package. Add a pair only after checking it.
REVIEWED_ALIASES: set[tuple[str, str]] = set()


def manifest_aliases(manifest: dict) -> set[tuple[str, str]]:
    """(folder, package) pairs that package.json declares."""
    pairs = set()
    for field in DEPENDENCY_FIELDS:
        for folder, spec in (manifest.get(field) or {}).items():
            if m := re.fullmatch(rf"npm:({NAME})(@.*)?", str(spec)):
                pairs.add((folder, m.group(1)))
    return pairs


def expected_url(name: str, version: str) -> str:
    """The registry tarball: <name>/-/<name without scope>-<version>.tgz."""
    return f"{REGISTRY}{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"


def problems(lock: dict, manifest: dict) -> list[str]:
    found = []
    if lock.get("lockfileVersion") != 3:
        found.append(f"lockfileVersion is {lock.get('lockfileVersion')}, expected 3")
    root = lock.get("packages", {}).get("", {})
    for field in DEPENDENCY_FIELDS:
        if (root.get(field) or {}) != (manifest.get(field) or {}):
            found.append(f"the lockfile's {field} don't match package.json")
    declared = manifest_aliases(manifest)
    for path, pkg in lock.get("packages", {}).items():
        if not path:
            continue  # the root project, checked above
        if pkg.get("link"):
            found.append(f"{path}: a link (this project has no workspaces)")
            continue
        if not PATH_KEY.fullmatch(path):
            found.append(f"{path}: not a plain node_modules path")
            continue
        folder = path.rsplit("node_modules/", 1)[-1]
        name, version = pkg.get("name", folder), str(pkg.get("version", ""))  # "name" only for aliases
        alias_ok = (folder, name) in REVIEWED_ALIASES or (
            path == f"node_modules/{folder}" and (folder, name) in declared
        )
        if name != folder and not (re.fullmatch(NAME, name) and alias_ok):
            found.append(f"{path}: named {name}, an alias not in package.json or REVIEWED_ALIASES")
        if not VERSION.fullmatch(version):
            found.append(f"{path}: version {version!r} isn't a plain semver version")
        resolved, integrity = pkg.get("resolved", ""), pkg.get("integrity", "")
        expected = expected_url(name, version)
        if resolved != expected:
            found.append(f"{path}: resolved from {resolved or 'nowhere'}, expected {expected}")
        if not integrity.startswith("sha512-"):
            found.append(f"{path}: no sha512 integrity hash")
    return found


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0] if argv else "package-lock.json")
    lock = json.loads(path.read_text())
    manifest = json.loads((path.parent / "package.json").read_text())
    found = problems(lock, manifest)
    for line in found:
        print(line)
    count = len(lock.get("packages", {})) - 1
    print(f"{len(found)} problems in {count} locked packages (each must be its own tarball on {REGISTRY})")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
