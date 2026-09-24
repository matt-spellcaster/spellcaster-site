"""check_branch_rules: the ruleset on main and the production environment meet every requirement."""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_branch_rules
from check_branch_rules import REQUIRED_CHECKS, REQUIRED_RULES, evaluate, evaluate_environment

RULESET = json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text())
RULES = RULESET["rules"]

REVIEWER = {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"login": "owner"}}]}


def environment(custom=True, branches=("main",), rules=(REVIEWER,)):
    return {
        "deployment_branch_policy": {"protected_branches": not custom, "custom_branch_policies": custom},
        "branch_policies": [{"name": b, "type": "branch"} for b in branches],
        "protection_rules": list(rules),
    }


def unmet(rows):
    return [row["requirement"] for row in rows if not row["met"]]


class Ruleset(unittest.TestCase):
    def test_committed_ruleset_is_active_on_main_with_no_bypass(self):
        # The live check can't see bypass actors (GET /rules/branches doesn't return them), and
        # this file is what gets PUT with an admin token, so it's checked here.
        self.assertEqual(RULESET["bypass_actors"], [])
        self.assertEqual(RULESET["enforcement"], "active")
        self.assertEqual(RULESET["conditions"]["ref_name"], {"include": ["~DEFAULT_BRANCH"], "exclude": []})
        checks = next(r for r in RULES if r["type"] == "required_status_checks")["parameters"]
        self.assertTrue(checks["strict_required_status_checks_policy"])
        self.assertEqual({c["integration_id"] for c in checks["required_status_checks"]}, {15368})  # GitHub Actions

    def test_committed_ruleset_meets_every_requirement(self):
        rows = evaluate(RULES)
        self.assertEqual(unmet(rows), [])
        self.assertEqual(len(rows), len(REQUIRED_RULES) + len(REQUIRED_CHECKS))

    def test_script_requires_everything_the_ruleset_sets(self):
        contexts = [c["context"] for r in RULES for c in r.get("parameters", {}).get("required_status_checks", [])]
        self.assertEqual(sorted(REQUIRED_CHECKS), sorted(contexts))
        self.assertEqual(sorted(REQUIRED_RULES), sorted(r["type"] for r in RULES))

    def test_each_rule_type_is_required(self):
        for rule_type, description in REQUIRED_RULES.items():
            with self.subTest(rule_type):
                self.assertIn(description, unmet(evaluate([r for r in RULES if r["type"] != rule_type])))

    def test_each_check_is_required(self):
        for name in REQUIRED_CHECKS:
            with self.subTest(name):
                rules = copy.deepcopy(RULES)
                for rule in rules:
                    checks = rule.get("parameters", {}).get("required_status_checks")
                    if checks is not None:
                        checks[:] = [c for c in checks if c["context"] != name]
                self.assertEqual(unmet(evaluate(rules)), [f"'{name}' is a required check"])


class Environment(unittest.TestCase):
    def test_main_only_with_a_reviewer(self):
        self.assertEqual(unmet(evaluate_environment(environment())), [])

    def test_no_policy_and_no_reviewers(self):
        rows = evaluate_environment({"deployment_branch_policy": None, "protection_rules": []})
        self.assertEqual(len(unmet(rows)), 2)
        self.assertEqual(rows[0]["detail"], "any branch")

    def test_branch_policy_must_be_main_alone(self):
        cases = {
            "main and another branch": environment(branches=("main", "release")),
            "protected branches": environment(custom=False),
            "no branches listed": environment(branches=()),
            "a tag named main": {**environment(), "branch_policies": [{"name": "main", "type": "tag"}]},
        }
        for label, env in cases.items():
            with self.subTest(label):
                self.assertEqual(unmet(evaluate_environment(env)), ["Only 'main' can deploy to 'production'"])

    def test_reviewer_rule_needs_a_reviewer(self):
        for rules in ((), ({"type": "wait_timer", "wait_timer": 5},), ({"type": "required_reviewers", "reviewers": []},)):
            with self.subTest(rules=rules):
                self.assertEqual(unmet(evaluate_environment(environment(rules=rules))),
                                 ["'production' deployments need a reviewer's approval"])

    def test_private_repository_waives_the_reviewer_and_says_so(self):
        # GitHub offers a required reviewer on a private repository only with Enterprise.
        rows = evaluate_environment(environment(rules=()), private=True)
        self.assertEqual(unmet(rows), [])
        self.assertTrue(rows[1]["waived"])
        self.assertIn("waived", rows[1]["detail"])

    def test_private_repository_with_a_reviewer_is_not_waived(self):
        rows = evaluate_environment(environment(), private=True)
        self.assertEqual(unmet(rows), [])
        self.assertNotIn("waived", rows[1])

    def test_private_repository_still_needs_main_only(self):
        self.assertEqual(unmet(evaluate_environment(environment(branches=("main", "release")), private=True)),
                         ["Only 'main' can deploy to 'production'"])


class Main(unittest.TestCase):
    def setUp(self):
        network = mock.patch.object(check_branch_rules, "get", side_effect=AssertionError("network call"))
        network.start()
        self.addCleanup(network.stop)

    def test_empty_branch_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
            check_branch_rules.main(["--repo", "o/r", "--branch", ""])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--branch is empty", err.getvalue())

    def test_missing_repo_is_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_REPOSITORY", None)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                check_branch_rules.main(["--branch", "main"])
        self.assertEqual(cm.exception.code, 2)

    def test_exit_code_and_evidence_file(self):
        cases = (
            (environment(), False, 0),
            (environment(rules=()), False, 1),
            (environment(rules=()), True, 0),  # private: the reviewer is waived and recorded
        )
        for env, private, expected in cases:
            with self.subTest(private=private, expected=expected), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "branch-rules.json"
                with mock.patch.object(check_branch_rules, "fetch_rules", return_value=RULES), \
                        mock.patch.object(check_branch_rules, "fetch_environment", return_value=env), \
                        mock.patch.object(check_branch_rules, "fetch_private", return_value=private), \
                        contextlib.redirect_stdout(io.StringIO()) as out_text:
                    code = check_branch_rules.main(["--repo", "o/r", "--branch", "main", "--out", str(out)])
                self.assertEqual(code, expected)
                evidence = json.loads(out.read_text())
                self.assertEqual(evidence["branch"], "main")
                self.assertEqual(evidence["private"], private)
                self.assertEqual(all(row["met"] for row in evidence["checks"]), expected == 0)
                self.assertEqual("waived" in out_text.getvalue(), private and expected == 0)


if __name__ == "__main__":
    unittest.main()
