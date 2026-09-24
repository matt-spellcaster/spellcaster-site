"""Check a Terraform plan before Deploy production applies it, and list what it changes.

    terraform show -json tfplan > plan.json
    python3 scripts/ci/plan_guard.py plan.json --summary "$GITHUB_STEP_SUMMARY"

Fails if the plan would delete, replace or forget a bucket or a distribution: the bucket holds
every published version of the site, and the distribution holds its domain names. The list
names each change by address and action only, never by value: CI logs and job summaries are
public, and values can name the account. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Resource types a deploy may create or update, but never remove.
PROTECTED = ("aws_s3_bucket", "aws_cloudfront_distribution")

# Terraform's action lists, as one word each.
ACTIONS = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
    ("forget",): "forget",
    ("create", "forget"): "replace",
}


def changes(plan: dict) -> list[tuple[str, str, str]]:
    """(address, resource type, action) for each managed resource the plan changes."""
    rows = []
    for rc in plan.get("resource_changes", []):
        actions = tuple(rc["change"]["actions"])
        if rc.get("mode") != "managed" or actions in (("no-op",), ("read",)):
            continue
        rows.append((rc["address"], rc["type"], ACTIONS.get(actions, "+".join(actions))))
    return rows


def refused(rows: list[tuple[str, str, str]]) -> list[str]:
    return [f"{address} ({action})" for address, rtype, action in rows
            if rtype in PROTECTED and action not in ("create", "update")]


def summary(rows: list[tuple[str, str, str]], problems: list[str]) -> str:
    lines = ["### Terraform plan", ""]
    if rows:
        lines += ["| Action | Resource |", "|---|---|"] + [f"| {action} | `{address}` |" for address, _, action in rows]
    else:
        lines.append("No changes.")
    if problems:
        lines += ["", "**Refused:** " + "; ".join(problems) + "."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plan", type=Path, help="output of terraform show -json <planfile>")
    p.add_argument("--summary", type=Path, help="markdown file to append to (the job summary)")
    args = p.parse_args(argv)

    rows = changes(json.loads(args.plan.read_text()))
    problems = refused(rows)
    for address, _, action in rows:
        print(f"{action:8} {address}")
    if args.summary:
        with args.summary.open("a") as f:
            f.write(summary(rows, problems))
    for problem in problems:
        print(f"::error::The plan would remove {problem}. A deploy never removes the site's bucket or "
              "distribution; if that's really meant, it's done by hand.", file=sys.stderr)
    print(f"{len(rows)} changes, {len(problems)} refused")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
