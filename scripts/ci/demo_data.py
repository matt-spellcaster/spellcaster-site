"""Bring the "Be the CISO" demo's data in from the tool, or check it is the tool's own output.

    python3 -I scripts/ci/demo_data.py sync --commit <sha>   # on the Mac: move the pin
    python3 -I scripts/ci/demo_data.py check                  # CI's Demo data job

Both clone the public tool repository, check out one commit, run its
scripts/export_demo.py (with `uv run --frozen`, so its own lockfile) and then either
write or compare these files:

    src/data/demo/<variant>.json              what the page is built from
    tests/fixtures/demo/<variant>.golden.json  what the page's replays must equal

check uses the commit the page data is stamped with (source.commit in web.json), so the
data can only be changed by moving the pin to another commit of the tool, never by hand.
The commit has to be on the tool's master branch. The export's PDFs are never copied:
the page links the sample report in the tool's repository instead.

sync runs the tool's code, and the packages its lockfile installs, in a throwaway container
that sees only the temporary folder (CLAUDE.md rule 1 keeps third-party code off the Mac).
check runs it directly: CI's Demo data job holds no secrets. sync needs git and Docker, check
needs git and uv. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = "matt-spellcaster/okta-access-review-aws"
BRANCH = "master"
VARIANTS = ("web",)
ROOT = Path(__file__).resolve().parents[2]
DATA = Path("src/data/demo")
GOLDEN = Path("tests/fixtures/demo")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
# uv at the version CI's Demo data job uses (a test checks), on the Python ubuntu-24.04 has.
# Not the slim image: the export runs git to stamp the commit it came from.
IMAGE = ("ghcr.io/astral-sh/uv:0.12.15-python3.12-trixie"
         "@sha256:1d5bc044746ddb1fafd9c7b62bd49f1e668809d0a4e022334b9135783ec0d367")

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


def contain(work: Path, command: list[str]) -> list[str]:
    """command, run in a throwaway container that sees only work (at /work), as this user."""
    return ["docker", "run", "--rm", "--pull", "missing", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/tmp", "--env", "UV_CACHE_DIR=/tmp/uv", "--env", "UV_PYTHON_DOWNLOADS=never",
            # The export runs git, which refuses a checkout mounted from outside as another's.
            "--env", "GIT_CONFIG_COUNT=1", "--env", "GIT_CONFIG_KEY_0=safe.directory",
            "--env", "GIT_CONFIG_VALUE_0=/work/tool",
            "--volume", f"{work}:/work", "--workdir", "/work/tool", IMAGE, *command]


def _read_plain(out: Path, name: str) -> bytes:
    """A file the export wrote, only if it is a plain JSON file in out: never through a link,
    which the tool's code could point at any file on the Mac."""
    try:
        if out.is_symlink():
            raise OSError
        fd = os.open(out / name, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise DemoDataError(f"the export wrote no {name}, or not as a plain file") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise DemoDataError(f"the export wrote no {name}, or not as a plain file")
        body = f.read()
    try:
        json.loads(body)
    except ValueError:
        raise DemoDataError(f"the export's {name} isn't JSON") from None
    return body


def export(commit: str, work: Path, run: Run = subprocess.run, contained: bool = False) -> dict[str, bytes]:
    """The export's files at this commit of the tool, by name. contained: run it in Docker."""
    if not COMMIT.match(commit):
        raise DemoDataError(f"not a full commit: {commit!r}")
    tool, out = work / "tool", work / "out"
    _run(run, "git", "clone", "--quiet", "--no-checkout", f"https://github.com/{REPO}.git", str(tool))
    _run(run, "git", "-C", str(tool), "checkout", "--quiet", "--detach", commit)
    if run(["git", "-C", str(tool), "merge-base", "--is-ancestor", commit, f"origin/{BRANCH}"],
           capture_output=True, text=True).returncode:
        raise DemoDataError(f"{commit} is not on {REPO}'s {BRANCH} branch")
    for variant in VARIANTS:
        command = ["uv", "run", "--frozen", "python", "scripts/export_demo.py", "--out",
                   "/work/out" if contained else str(out), "--variant", variant]
        _run(run, *(contain(work, command) if contained else command), cwd=tool)
    files = {name: _read_plain(out, name) for name in targets()}
    try:
        stamped = json.loads(files[f"{VARIANTS[0]}.json"])["source"]["commit"]
    except (ValueError, KeyError, TypeError):
        raise DemoDataError(f"the export's {VARIANTS[0]}.json has no source.commit") from None
    if stamped != commit:
        raise DemoDataError(f"the export is stamped {stamped!r}, not {commit}")
    return files


def committed(root: Path = ROOT) -> dict[str, bytes | None]:
    """The committed files, by the export's name for them (None when missing)."""
    return {name: (root / rel).read_bytes() if (root / rel).is_file() else None
            for name, rel in targets().items()}


def differences(files: dict[str, bytes], before: dict[str, bytes | None]) -> list[str]:
    """Each committed file that isn't byte for byte what the export wrote."""
    out = []
    for name, rel in targets().items():
        if before[name] is None:
            out.append(f"{rel} is missing")
        elif before[name] != files[name]:
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
        # Read before the tool's code runs, so nothing it does can make the files match.
        before = committed(root)
        with tempfile.TemporaryDirectory() as tmp:
            files = export(commit, Path(tmp), run, contained=args.command == "sync")
        if args.command == "sync":
            for rel in write(files, root):
                print(f"wrote {rel}")
            return 0
        problems = differences(files, before)
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
