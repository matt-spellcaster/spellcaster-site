"""Refuse PDFs: this public repository holds none.

    python3 -I scripts/ci/check_pdfs.py --staged    # what `git commit` is about to add (the hook)
    python3 -I scripts/ci/check_pdfs.py --history   # every file on every branch and tag (CI)

Matthew's resume stays off the site, and no other PDF belongs here. A PDF keeps its text
compressed, so no line scan (the hook's, or gitleaks') can read what's inside one, and
reading PDFs well enough to trust is a project of its own. So this refuses them all. A file
is a PDF if its name ends in .pdf or a PDF header starts in its first 1024 bytes, which is
where PDF writers put it and as far as Acrobat looks. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# In two pieces, so this file doesn't carry the header it looks for.
HEADER = b"%" b"PDF-"
HEADER_WINDOW = 1024  # a header must start in this many bytes
SUBMODULE = "160000"


def git(*args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], input=stdin, check=True, capture_output=True).stdout


def staged() -> list[tuple[str, str]]:
    """(blob sha, path) for each file added or changed in the index, rename or not."""
    out = git("diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "--no-relative",
              "--no-ext-diff", "--diff-filter=d").split(b"\0")
    # -z gives ":<old mode> <new mode> <old sha> <new sha> <status>", then the path.
    return [
        (meta.split()[3].decode(), path.decode("utf-8", "surrogateescape"))
        for meta, path in zip(out[::2], out[1::2])
        if meta and meta.split()[1].decode() != SUBMODULE
    ]


def history() -> list[tuple[str, str]]:
    """(blob sha, path) for every file on every branch and tag. Git lists each blob once, under
    the first path it meets, so a copy under another name is covered by the header rule."""
    out = git("rev-list", "--objects", "--all", "--filter=object:type=blob", "-z").split(b"\0")
    # -z gives each object's sha, followed by "path=<path>" when it has one. A blob a tag points
    # at directly has no path.
    found = []
    for sha, after in zip(out, [*out[1:], b""]):
        if sha and not sha.startswith(b"path="):
            path = after.removeprefix(b"path=") if after.startswith(b"path=") else b""
            found.append((sha.decode(), path.decode("utf-8", "surrogateescape")))
    return found


def heads(shas: set[str]) -> dict[str, bytes]:
    """The first bytes of each blob, read through one git process."""
    out = git("cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in shas).encode())
    found, i = {}, 0
    while i < len(out):
        end = out.index(b"\n", i)
        sha, kind, *size = out[i:end].decode().split()
        if kind == "missing":
            raise RuntimeError(f"git has no object {sha}")
        start = end + 1
        if kind == "blob":
            found[sha] = out[start : start + min(int(size[0]), HEADER_WINDOW + len(HEADER) - 1)]
        i = start + int(size[0]) + 1
    return found


def shown(path: str) -> str:
    """A path safe to print in a CI log: on one line, and never read as a workflow command."""
    return repr(path)[1:-1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check the files staged for commit")
    mode.add_argument("--history", action="store_true", help="check every file on every branch and tag")
    args = p.parse_args(argv)
    files = staged() if args.staged else history()
    first_bytes = heads({sha for sha, _ in files})
    checked = found = 0
    for sha, path in files:
        if sha not in first_bytes:  # not a blob
            continue
        checked += 1
        by_name, by_header = path.lower().endswith(".pdf"), HEADER in first_bytes[sha]
        if by_name or by_header:
            found += 1
            why = "its name" if by_name else "its header"
            where = f"{shown(path)} (blob {sha[:12]})" if args.history else shown(path)
            print(f"PDF: {where}, by {why}. No PDF belongs in this repository (CLAUDE.md rule 7).")
    print(f"{checked} files checked, {found} PDFs found")
    return 1 if found else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # exit 1 means "a PDF was found", so a crash must not use it
        print(f"check_pdfs.py failed: {type(e).__name__}: {e}", file=sys.stderr)
        code = 2
    raise SystemExit(code)
