"""Check that the default branch and the production environment are protected.

Reads GET /repos/{repo}/rules/branches/{branch} and the production environment's
settings, which only need read access, so the workflow's GITHUB_TOKEN is enough.
Writes what it found as evidence and exits 1 if a required protection is missing.

    python3 scripts/ci/check_branch_rules.py --repo owner/name --branch main
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REQUIRED_RULES = {
    "pull_request": "Changes reach the branch only through a pull request",
    "required_status_checks": "Required checks must pass before merging",
    "non_fast_forward": "Force pushes are blocked",
    "deletion": "The branch can't be deleted",
    "required_linear_history": "History stays linear (squash merges only)",
}
# Job names from .github/workflows/compliance.yml that must be required checks.
REQUIRED_CHECKS = ["Build", "E2E", "Security", "Evidence"]
# Deploy production runs in this environment; only this branch may deploy to it.
ENVIRONMENT = "production"
DEPLOY_BRANCH = "main"


def get(path: str, token: str, api: str = "https://api.github.com"):
    req = urllib.request.Request(
        f"{api}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_rules(repo: str, branch: str, token: str) -> list[dict]:
    rules: list[dict] = []
    page = 1
    while True:
        batch = get(f"/repos/{repo}/rules/branches/{branch}?per_page=100&page={page}", token)
        rules.extend(batch)
        if len(batch) < 100:
            return rules
        page += 1


def fetch_environment(repo: str, token: str) -> dict:
    """The environment's settings plus its deployment branch policies."""
    env = get(f"/repos/{repo}/environments/{ENVIRONMENT}", token)
    policy = env.get("deployment_branch_policy") or {}
    env["branch_policies"] = (
        get(f"/repos/{repo}/environments/{ENVIRONMENT}/deployment-branch-policies?per_page=100", token)
        .get("branch_policies", [])
        if policy.get("custom_branch_policies") else []
    )
    return env


def evaluate_environment(env: dict) -> list[dict]:
    policy = env.get("deployment_branch_policy") or {}
    branches = sorted(f"{p.get('type', 'branch')}:{p.get('name')}" for p in env.get("branch_policies", []))
    only_main = bool(policy.get("custom_branch_policies")) and branches == [f"branch:{DEPLOY_BRANCH}"]
    reviewers = [
        r for rule in env.get("protection_rules", []) if rule.get("type") == "required_reviewers"
        for r in rule.get("reviewers", [])
    ]
    return [
        {"requirement": f"Only '{DEPLOY_BRANCH}' can deploy to '{ENVIRONMENT}'", "rule": "environment",
         "met": only_main, "detail": ", ".join(branches) or "any branch"},
        {"requirement": f"'{ENVIRONMENT}' deployments need a reviewer's approval", "rule": "environment",
         "met": bool(reviewers), "detail": f"{len(reviewers)} required reviewer(s)"},
    ]


def evaluate(rules: list[dict]) -> list[dict]:
    """One row per requirement: what's required, whether it's met, and why."""
    by_type: dict[str, list[dict]] = {}
    for rule in rules:
        by_type.setdefault(rule.get("type", ""), []).append(rule)

    rows = []
    for rule_type, description in REQUIRED_RULES.items():
        present = rule_type in by_type
        rows.append({"requirement": description, "rule": rule_type, "met": present,
                     "detail": "present" if present else "missing"})

    contexts = {
        check.get("context")
        for rule in by_type.get("required_status_checks", [])
        for check in rule.get("parameters", {}).get("required_status_checks", [])
    }
    for name in REQUIRED_CHECKS:
        met = name in contexts
        rows.append({"requirement": f"'{name}' is a required check", "rule": "required_status_checks",
                     "met": met, "detail": "required" if met else "not required"})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p.add_argument("--branch", required=True)
    p.add_argument("--out", type=Path, default=Path("results/branch-rules.json"))
    args = p.parse_args(argv)
    if not args.repo:
        p.error("--repo is required outside GitHub Actions")
    if not args.branch:
        p.error("--branch is empty")

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        rules = fetch_rules(args.repo, args.branch, token)
        environment = fetch_environment(args.repo, token)
    except urllib.error.HTTPError as e:
        print(f"could not read branch rules or the {ENVIRONMENT} environment: HTTP {e.code}", file=sys.stderr)
        return 2
    rows = evaluate(rules) + evaluate_environment(environment)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"repo": args.repo, "branch": args.branch, "checks": rows, "rules": rules,
                                    "environment": environment}, indent=2) + "\n")
    for row in rows:
        print(f"{'ok     ' if row['met'] else 'MISSING'}  {row['requirement']}")
    return 0 if all(row["met"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
