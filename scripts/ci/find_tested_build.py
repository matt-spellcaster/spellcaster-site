"""Find the Compliance run whose tested site QA should publish, for one commit.

    python3 scripts/ci/find_tested_build.py --repo owner/name --sha <commit>

Prints the ID of the newest Compliance run for that commit whose Build and E2E jobs passed
and whose site-dist artifact hasn't expired. QA publishes exactly those bytes, the same way
Deploy production does, so nothing is ever built twice. A pull request's run counts: it
builds the branch merged with main as it was then.

Needs a token that can read Actions (GITHUB_TOKEN with actions: read). Exits 1, saying what
to do, when there's no such run. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from check_branch_rules import get  # same folder

WORKFLOW = "compliance.yml"
ARTIFACT = "site-dist"
TESTED_BY = ("Build", "E2E")

Get = Callable[[str], object]


def passed(jobs: list[dict]) -> bool:
    conclusions = {job["name"]: job.get("conclusion") for job in jobs}
    return all(conclusions.get(name) == "success" for name in TESTED_BY)


def find(repo: str, sha: str, api: Get) -> tuple[int | None, list[str]]:
    """The run's ID, or None and why each candidate was passed over."""
    runs = api(f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs?head_sha={sha}&per_page=100")["workflow_runs"]
    notes = []
    for run in sorted(runs, key=lambda r: r["created_at"], reverse=True):
        label = f"run {run['id']} ({run['event']})"
        if (run.get("head_repository") or {}).get("full_name") != repo:
            notes.append(f"{label}: from another repository")
            continue
        jobs = api(f"/repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
        if not passed(jobs):
            notes.append(f"{label}: Build and E2E haven't both passed")
            continue
        artifacts = api(f"/repos/{repo}/actions/runs/{run['id']}/artifacts?name={ARTIFACT}")["artifacts"]
        if not any(not a["expired"] for a in artifacts):
            notes.append(f"{label}: its {ARTIFACT} artifact has expired")
            continue
        return run["id"], notes
    return None, notes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    p.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    args = p.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")

    run_id, notes = find(args.repo, args.sha, lambda path: get(path, token))
    for note in notes:
        print(f"passed over {note}", file=sys.stderr)
    if run_id is None:
        print(f"::error::No tested build of {args.sha}. QA publishes what the Compliance workflow built and "
              "tested: open a pull request for this branch (or push to it again), wait for Build and E2E to pass, "
              "then run QA up again. A build is kept for 30 days.", file=sys.stderr)
        return 1
    print(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
