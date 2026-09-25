"""Publish the tested site to its bucket, then clear CloudFront's cache.

    python3 scripts/ci/publish_site.py --dist site/dist --bucket <bucket> --distribution-id <id>

1. Uploads every file with its own Content-Type and Cache-Control. Files under _astro/ have
   a content hash in their names, so browsers keep them for a year; everything else is
   checked again on each visit, and CloudFront keeps it a day (the invalidation clears it).
   _astro goes first and HTML last, so no page ever names a file that isn't there yet.
2. Deletes what the build no longer has, except old _astro files: a page that's still open
   in someone's browser, or still cached at an edge, may ask for one. Their names never clash,
   and in production's versioned bucket a delete would free no space anyway.
3. Invalidates /* and waits until CloudFront has finished.

Runs the AWS CLI (preinstalled on GitHub's runners) with the job's credentials. Standard
library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json",
}
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "public, max-age=0, s-maxage=86400, must-revalidate"
# Names go to the AWS CLI as --include patterns, so none may hold a pattern character.
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


@dataclass
class Group:
    content_type: str
    cache_control: str
    files: list[str] = field(default_factory=list)


def is_asset(key: str) -> bool:
    return key.startswith("_astro/")


def plan_uploads(files: list[str]) -> list[Group]:
    """One group per (Content-Type, Cache-Control): _astro first, then the rest, HTML last."""
    groups: dict[tuple[str, str], Group] = {}
    for name in sorted(files):
        if not SAFE_NAME.fullmatch(name) or {".", ".."} & set(name.split("/")):
            raise ValueError(f"unexpected characters in a file name: {name!r}")
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in CONTENT_TYPES:
            raise ValueError(f"no Content-Type for {name!r}; add its extension to CONTENT_TYPES")
        key = (CONTENT_TYPES[suffix], IMMUTABLE if is_asset(name) else REVALIDATE)
        groups.setdefault(key, Group(*key)).files.append(name)

    def order(g: Group) -> tuple[int, str]:
        return (0 if g.cache_control == IMMUTABLE else 2 if g.content_type.startswith("text/html") else 1, g.content_type)

    return sorted(groups.values(), key=order)


def stale_keys(existing: list[str], current: set[str]) -> tuple[list[str], int]:
    """Keys to delete, and how many old _astro files are kept."""
    old = [key for key in existing if key not in current]
    delete = [key for key in old if not is_asset(key)]
    return delete, len(old) - len(delete)


class Aws:
    def __call__(self, *args: str) -> str:
        done = subprocess.run(["aws", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"aws {' '.join(args[:2])} failed ({done.returncode}): {done.stderr.strip()}")
        return done.stdout


def publish(dist: Path, bucket: str, distribution_id: str, aws=None) -> str:
    aws = aws or Aws()
    files = [p.relative_to(dist).as_posix() for p in sorted(dist.rglob("*")) if p.is_file()]
    if "index.html" not in files:
        raise ValueError(f"{dist}/index.html is missing")

    groups = plan_uploads(files)
    for g in groups:
        includes = [arg for name in g.files for arg in ("--include", name)]
        aws("s3", "cp", str(dist), f"s3://{bucket}/", "--recursive", "--exclude", "*", *includes,
            "--content-type", g.content_type, "--cache-control", g.cache_control,
            "--only-show-errors", "--no-progress")

    listing = aws("s3api", "list-objects-v2", "--bucket", bucket, "--output", "json",
                  "--query", "Contents[].Key")
    delete, kept = stale_keys(json.loads(listing or "null") or [], set(files))
    for start in range(0, len(delete), 1000):  # delete-objects takes up to 1000 keys
        batch = {"Objects": [{"Key": k} for k in delete[start:start + 1000]], "Quiet": True}
        errors = json.loads(aws("s3api", "delete-objects", "--bucket", bucket, "--delete", json.dumps(batch),
                                "--output", "json") or "{}").get("Errors")
        if errors:
            raise RuntimeError(f"could not delete {len(errors)} old files: {errors[:3]}")

    invalidation = aws("cloudfront", "create-invalidation", "--distribution-id", distribution_id,
                       "--paths", "/*", "--query", "Invalidation.Id", "--output", "text").strip()
    aws("cloudfront", "wait", "invalidation-completed", "--distribution-id", distribution_id, "--id", invalidation)

    return (f"{len(files)} files uploaded in {len(groups)} groups; {len(delete)} old files deleted, "
            f"{kept} old _astro files kept; invalidation {invalidation} complete")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dist", type=Path, required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--distribution-id", required=True)
    args = p.parse_args(argv)
    print(publish(args.dist, args.bucket, args.distribution_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
