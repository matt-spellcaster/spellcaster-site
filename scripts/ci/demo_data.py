"""Bring the "Be the CISO" demo's data in from the tool, or check it is the tool's own output.

    python3 -I scripts/ci/demo_data.py sync --commit <sha>   # on the Mac: move the pin
    python3 -I scripts/ci/demo_data.py check                  # CI's Demo data job

Both clone the public tool repository, check out one commit, run its
scripts/export_demo.py (with `uv run --frozen`, so its own lockfile) and then either
write or compare these files:

    src/data/demo/<variant>.json              what the page is built from
    tests/fixtures/demo/<variant>.golden.json  what the page's replays must equal

check uses the commit the page data is stamped with (source.commit in okta.json), so the
data can only be changed by moving the pin to another commit of the tool, never by hand.
The commit has to be on the tool's master branch. The export's PDFs are never copied:
the page links the sample report in the tool's repository instead.

Needs git and uv. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = "matt-spellcaster/okta-access-review-aws"
BRANCH = "master"
VARIANTS = ("okta",)
ROOT = Path(__file__).resolve().parents[2]
DATA = Path("src/data/demo")
GOLDEN = Path("tests/fixtures/demo")
COMMIT = re.compile(r"^[0-9a-f]{40}$")

Run = Callable[..., subprocess.CompletedProcess]


class DemoDataError(Exception):
    pass


def targets() -> dict[str, Path]:
    """The export's file name, and where it goes in this repository."""
    out = {}
    for v in VARIANTS:
        out[f"{v}.json"] = DATA / f"{v}.json"
        out[f"{v}.golden.json"] = GOLDEN / f"{v}.golden.json"
    return out


def pinned(root: Path = ROOT) -> str:
    """The tool commit the committed page data says it came from."""
    path = root / DATA / f"{VARIANTS[0]}.json"
    try:
        commit = json.loads(path.read_text(encoding="utf-8"))["source"]["commit"]
    except (OSError, ValueError, KeyError, TypeError):
        raise DemoDataError(f"{path} can't be read, or has no source.commit") from None
    if not isinstance(commit, str) or not COMMIT.match(commit):
        raise DemoDataError(f"{path} names no full commit: {commit!r}")
    return commit


def _run(run: Run, *args: str, cwd: Path | None = None) -> str:
    done = run(list(args), cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise DemoDataError(f"{' '.join(args[:3])} failed: {(done.stderr or done.stdout).strip()[-2000:]}")
    return done.stdout


def export(commit: str, work: Path, run: Run = subprocess.run) -> dict[str, bytes]:
    """The export's files at this commit of the tool, by name."""
    if not COMMIT.match(commit):
        raise DemoDataError(f"not a full commit: {commit!r}")
    tool, out = work / "tool", work / "out"
    _run(run, "git", "clone", "--quiet", "--no-checkout", f"https://github.com/{REPO}.git", str(tool))
    _run(run, "git", "-C", str(tool), "checkout", "--quiet", "--detach", commit)
    if run(["git", "-C", str(tool), "merge-base", "--is-ancestor", commit, f"origin/{BRANCH}"],
           capture_output=True, text=True).returncode:
        raise DemoDataError(f"{commit} is not on {REPO}'s {BRANCH} branch")
    for variant in VARIANTS:
        _run(run, "uv", "run", "--frozen", "python", "scripts/export_demo.py", "--out", str(out),
             "--variant", variant, cwd=tool)
    files = {}
    for name in targets():
        try:
            files[name] = (out / name).read_bytes()
        except OSError:
            raise DemoDataError(f"the export wrote no {name}") from None
    stamped = json.loads(files[f"{VARIANTS[0]}.json"])["source"]["commit"]
    if stamped != commit:
        raise DemoDataError(f"the export is stamped {stamped!r}, not {commit}")
    return files


def differences(files: dict[str, bytes], root: Path = ROOT) -> list[str]:
    """Each committed file that isn't byte for byte what the export wrote."""
    out = []
    for name, rel in targets().items():
        path = root / rel
        if not path.is_file():
            out.append(f"{rel} is missing")
        elif path.read_bytes() != files[name]:
            out.append(f"{rel} differs from the export")
    return out


def write(files: dict[str, bytes], root: Path = ROOT) -> list[Path]:
    written = []
    for name, rel in targets().items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(files[name])
        written.append(rel)
    return written


def main(argv: list[str] | None = None, run: Run = subprocess.run, root: Path = ROOT) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sync", help="export at a commit and write the files")
    s.add_argument("--commit", required=True, help="the full commit of the tool to pin")
    sub.add_parser("check", help="export at the pinned commit and compare")
    args = p.parse_args(argv)
    try:
        commit = args.commit if args.command == "sync" else pinned(root)
        with tempfile.TemporaryDirectory() as tmp:
            files = export(commit, Path(tmp), run)
        if args.command == "sync":
            for rel in write(files, root):
                print(f"wrote {rel}")
            return 0
        problems = differences(files, root)
    except DemoDataError as e:
        print(f"demo_data: {e}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(f"demo_data: the demo data isn't {REPO}'s export at {commit}. "
              f"Run scripts/ci/demo_data.py sync --commit <sha> on the Mac, never edit it by hand.",
              file=sys.stderr)
        return 1
    print(f"{len(targets())} files match {REPO}'s export at {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
