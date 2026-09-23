"""Write, or check, dist-manifest.json: the SHA-256 of every file in the built site.

    python3 scripts/ci/dist_manifest.py dist dist-manifest.json          # write
    python3 scripts/ci/dist_manifest.py --check dist dist-manifest.json  # compare

Later jobs test and publish this exact artifact; --check proves the files they have
are the ones the Build job hashed. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from record import run_metadata  # same folder


def hash_tree(dist: Path) -> dict[str, str]:
    return {
        path.relative_to(dist).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(dist.rglob("*"))
        if path.is_file()
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dist", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("--check", action="store_true", help="compare dist against an existing manifest")
    args = p.parse_args(argv)

    files = hash_tree(args.dist)
    if "index.html" not in files:
        print(f"{args.dist}/index.html is missing; build the site first", file=sys.stderr)
        return 1

    if args.check:
        expected = json.loads(args.manifest.read_text())["files"]
        changed = sorted(f for f in expected.keys() & files.keys() if expected[f] != files[f])
        for label, names in (("missing", sorted(expected.keys() - files.keys())),
                             ("unexpected", sorted(files.keys() - expected.keys())), ("changed", changed)):
            for name in names:
                print(f"{label}: {name}", file=sys.stderr)
        ok = expected == files
        print(f"{len(files)} files {'match' if ok else 'do NOT match'} {args.manifest}")
        return 0 if ok else 1

    manifest = {"run": run_metadata(), "file_count": len(files), "files": files}
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(files)} files hashed -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
