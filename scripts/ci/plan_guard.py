"""Check a Terraform plan before Deploy production applies it, and list what it changes.

    terraform show -json tfplan > plan.json
    python3 scripts/ci/plan_guard.py plan.json --summary "$GITHUB_STEP_SUMMARY"

Fails if the plan would delete, replace or forget a bucket or a distribution: the bucket holds
every published version of the site, and the distribution holds its domain names. It also fails
if the plan would remove or turn off what keeps the bucket private and its old versions kept:
its versioning, public access block and policy. The list names each change by address and
action only, never by value: CI logs and job summaries are public, and values can name the
account. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Resource types a deploy may create or update, but never remove.
PROTECTED = ("aws_s3_bucket", "aws_cloudfront_distribution", "aws_s3_bucket_versioning",
             "aws_s3_bucket_public_access_block", "aws_s3_bucket_policy")
BLOCK_FLAGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")

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


def changes(plan: dict) -> list[dict]:
    """address, type, action, the resource's settings after the change and Terraform's reason,
    for each managed resource the plan changes."""
    rows = []
    for rc in plan.get("resource_changes", []):
        actions = tuple(rc["change"]["actions"])
        if rc.get("mode") != "managed" or actions in (("no-op",), ("read",)):
            continue
        rows.append({"address": rc["address"], "type": rc["type"], "action": ACTIONS.get(actions, "+".join(actions)),
                     "after": rc["change"].get("after") or {}, "reason": rc.get("action_reason")})
    return rows


def weakens(rtype: str, after: dict) -> str | None:
    """What a create or update turns off, if it's versioning or the public access block."""
    if rtype == "aws_s3_bucket_versioning":
        status = ((after.get("versioning_configuration") or [{}])[0]).get("status")
        return None if status == "Enabled" else f"versioning {status}"
    if rtype == "aws_s3_bucket_public_access_block":
        off = [flag for flag in BLOCK_FLAGS if after.get(flag) is not True]
        return ", ".join(off) + " off" if off else None
    return None


def refused(rows: list[dict]) -> list[str]:
    problems = []
    for row in rows:
        if row["type"] not in PROTECTED:
            continue
        if row["action"] not in ("create", "update"):
            # A distribution whose first create timed out is tainted: docs/aws.md says what to do.
            tainted = ", tainted" if row["reason"] == "replace_because_tainted" else ""
            problems.append(f"{row['address']} ({row['action']}{tainted})")
        elif weakness := weakens(row["type"], row["after"]):
            problems.append(f"{row['address']} ({weakness})")
    return problems


def summary(rows: list[dict], problems: list[str]) -> str:
    lines = ["### Terraform plan", ""]
    if rows:
        lines += ["| Action | Resource |", "|---|---|"] + [f"| {r['action']} | `{r['address']}` |" for r in rows]
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
    for row in rows:
        print(f"{row['action']:8} {row['address']}")
    if args.summary:
        with args.summary.open("a") as f:
            f.write(summary(rows, problems))
    for problem in problems:
        print(f"::error::The plan would remove or weaken {problem}. A deploy never removes the site's bucket, "
              "its distribution or the bucket's protections; if that's really meant, it's done by hand "
              "(docs/aws.md).", file=sys.stderr)
    print(f"{len(rows)} changes, {len(problems)} refused")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
