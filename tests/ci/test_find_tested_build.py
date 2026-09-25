"""find_tested_build: QA gets the newest run of this commit that built and tested the site."""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import find_tested_build

REPO, SHA = "matt-spellcaster/spellcaster-site-WIP", "a" * 40


def run(run_id, created, event="pull_request", repo=REPO):
    return {"id": run_id, "created_at": created, "event": event, "head_repository": {"full_name": repo}}


def jobs(**conclusions):
    return {"jobs": [{"name": name, "conclusion": c} for name, c in conclusions.items()]}


class FakeApi:
    def __init__(self, runs, jobs_by_run, artifacts_by_run):
        self.runs, self.jobs, self.artifacts = runs, jobs_by_run, artifacts_by_run
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        if "/workflows/compliance.yml/runs?head_sha=" in path:
            return {"workflow_runs": self.runs}
        run_id = int(path.split("/runs/")[1].split("/")[0])
        if "/jobs?" in path:
            return self.jobs[run_id]
        return {"artifacts": [{"name": "site-dist", "expired": e} for e in self.artifacts[run_id]]}


GREEN = jobs(Build="success", E2E="success", Security="failure")


class FindTestedBuild(unittest.TestCase):
    def test_the_newest_tested_run_wins_even_if_another_check_failed(self):
        api = FakeApi([run(1, "2026-09-01T00:00:00Z"), run(2, "2026-09-02T00:00:00Z", "push")],
                      {1: GREEN, 2: GREEN}, {1: [False], 2: [False]})
        self.assertEqual(find_tested_build.find(REPO, SHA, api), (2, []))
        self.assertIn(f"head_sha={SHA}", api.paths[0])

    def test_untested_expired_and_foreign_runs_are_passed_over(self):
        api = FakeApi(
            [run(1, "2026-09-04T00:00:00Z"), run(2, "2026-09-03T00:00:00Z", repo="someone/fork"),
             run(3, "2026-09-02T00:00:00Z"), run(4, "2026-09-01T00:00:00Z")],
            {1: jobs(Build="success", E2E="failure"), 3: GREEN, 4: GREEN},
            {3: [True], 4: [False]})
        run_id, notes = find_tested_build.find(REPO, SHA, api)
        self.assertEqual(run_id, 4)
        self.assertEqual(notes, ["run 1 (pull_request): Build and E2E haven't both passed",
                                 "run 2 (pull_request): from another repository",
                                 "run 3 (pull_request): its site-dist artifact has expired"])

    def test_a_run_still_waiting_on_e2e_is_not_tested(self):
        self.assertFalse(find_tested_build.passed(jobs(Build="success", E2E=None)["jobs"]))
        self.assertFalse(find_tested_build.passed(jobs(Build="success")["jobs"]))

    def test_no_run_says_to_open_a_pull_request(self):
        api = FakeApi([], {}, {})
        with mock.patch.object(find_tested_build, "get", lambda path, token: api(path)), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = find_tested_build.main(["--repo", REPO, "--sha", SHA])
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertIn("open a pull request for this branch", err.getvalue())

    def test_prints_only_the_run_id(self):
        api = FakeApi([run(7, "2026-09-01T00:00:00Z")], {7: GREEN}, {7: [False]})
        with mock.patch.object(find_tested_build, "get", lambda path, token: api(path)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(find_tested_build.main(["--repo", REPO, "--sha", SHA]), 0)
        self.assertEqual(out.getvalue(), "7\n")


if __name__ == "__main__":
    unittest.main()
