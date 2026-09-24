"""record: the exit code decides pass or fail, and check names stay safe to use as file names."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

from record import build_record


def make(check="tests", code=0, title="Tests", env=None):
    return build_record(check, code, title, ["SOC 2 CC8.1"], "tool", "detail", env={} if env is None else env)


class BuildRecord(unittest.TestCase):
    def test_exit_code_sets_status(self):
        for code, status in ((0, "pass"), (1, "fail"), (2, "fail"), (-9, "fail")):
            with self.subTest(code=code):
                result = make(code=code)
                self.assertEqual((result["status"], result["exit_code"]), (status, code))

    def test_title_and_run_metadata(self):
        result = make(title="", env={"GITHUB_SHA": "abc123", "GITHUB_REF": "refs/heads/main"})
        self.assertEqual(result["title"], "tests")
        self.assertEqual((result["run"]["sha"], result["run"]["ref"], result["run"]["actor"]),
                         ("abc123", "refs/heads/main", ""))

    def test_valid_check_names(self):
        for check in ("secret-scan", "e2e", "a"):
            with self.subTest(check):
                self.assertEqual(make(check)["check"], check)

    def test_invalid_check_names(self):
        for check in ("Tests", "-tests", "secret scan", "", "tests\n", "tests_1", "../escape", "a/b"):
            with self.subTest(check=check), self.assertRaises(ValueError):
                make(check)


if __name__ == "__main__":
    unittest.main()
