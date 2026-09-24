"""iam_policy_tests: the trust check, the case list and the report, without AWS."""

import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import iam_policy_tests as t

BOOTSTRAP = ROOT / "infra" / "bootstrap"
ACCOUNT = "ACCOUNTID"  # a stand-in: nothing here may look like a real account ID
ZONE = "ZEXAMPLE"


def trust(env, **changes):
    statement = {
        "Effect": "Allow",
        "Principal": {"Federated": f"arn:aws:iam::{ACCOUNT}:oidc-provider/{t.OIDC_HOST}"},
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
            "StringEquals": {f"{t.OIDC_HOST}:aud": "sts.amazonaws.com"},
            "StringLike": {f"{t.OIDC_HOST}:sub": t.subject(env)},
        },
    }
    statement.update(changes)
    return {"Version": "2012-10-17", "Statement": [statement]}


def default(variable):
    """A variable's default in infra/bootstrap/variables.tf."""
    text = (BOOTSTRAP / "variables.tf").read_text()
    block = re.search(r'variable "%s" \{(.*?)\n\}' % variable, text, re.S).group(1)
    return re.search(r"default\s*=\s*(.+)", block).group(1).strip().strip('"')


class MatchesTerraform(unittest.TestCase):
    def test_ids_domain_and_owner_match_the_bootstrap_variables(self):
        self.assertEqual(int(default("github_owner_id")), t.OWNER_ID)
        self.assertEqual(int(default("github_repo_id")), t.REPO_ID)
        self.assertEqual(default("domain"), t.DOMAIN)
        self.assertEqual(default("region"), t.REGION)
        self.assertEqual(default("github_repository").split("/")[0], t.OWNER)

    def test_role_names_and_tag_keys_match(self):
        main = (BOOTSTRAP / "main.tf").read_text()
        for name in t.ROLES.values():
            self.assertIn(f'role      = "{name}"', main)
        keys = re.search(r"tag_keys = \[(.*?)\]", main).group(1)
        self.assertEqual(re.findall(r'"(\w+)"', keys), t.TAG_KEYS)
        versions = (BOOTSTRAP / "versions.tf").read_text()
        for key in t.TAG_KEYS:
            self.assertRegex(versions, rf"\n\s+{key}\s+=")

    def test_trust_subject_matches(self):
        roles = (BOOTSTRAP / "ci_roles.tf").read_text()
        self.assertIn('subject_prefix = "repo:${local.owner}@${var.github_owner_id}/*@${var.github_repo_id}"', roles)
        self.assertIn('"${local.subject_prefix}:environment:${each.key}"', roles)


class Trust(unittest.TestCase):
    def test_accepts_the_expected_policy(self):
        for env in t.ROLES:
            self.assertEqual(t.check_trust(trust(env), env, ACCOUNT), [])

    def test_accepts_single_values_written_as_lists(self):
        doc = trust("qa", Action=["sts:AssumeRoleWithWebIdentity"], Condition={
            "StringEquals": {f"{t.OIDC_HOST}:aud": ["sts.amazonaws.com"]},
            "StringLike": {f"{t.OIDC_HOST}:sub": [t.subject("qa")]},
        })
        self.assertEqual(t.check_trust(doc, "qa", ACCOUNT), [])

    def test_rejects_the_other_environment(self):
        self.assertTrue(t.check_trust(trust("qa"), "production", ACCOUNT))

    def test_rejects_a_wider_subject(self):
        doc = trust("qa", Condition={
            "StringEquals": {f"{t.OIDC_HOST}:aud": "sts.amazonaws.com"},
            "StringLike": {f"{t.OIDC_HOST}:sub": f"repo:{t.OWNER}@{t.OWNER_ID}/*"},
        })
        self.assertTrue(t.check_trust(doc, "qa", ACCOUNT))

    def test_rejects_a_missing_audience(self):
        doc = trust("qa", Condition={"StringLike": {f"{t.OIDC_HOST}:sub": t.subject("qa")}})
        self.assertTrue(t.check_trust(doc, "qa", ACCOUNT))

    def test_rejects_other_principals_actions_and_statements(self):
        self.assertTrue(t.check_trust(trust("qa", Principal={"AWS": "*"}), "qa", ACCOUNT))
        self.assertTrue(t.check_trust(trust("qa", Action="sts:*"), "qa", ACCOUNT))
        self.assertTrue(t.check_trust(trust("qa", Effect="Deny"), "qa", ACCOUNT))
        doc = trust("qa")
        doc["Statement"].append(doc["Statement"][0])
        self.assertTrue(t.check_trust(doc, "qa", ACCOUNT))


class Cases(unittest.TestCase):
    def test_every_case_is_well_formed(self):
        arns = t.resources(ACCOUNT, ZONE)
        for c in t.CASES:
            with self.subTest(c=c):
                self.assertIn(c.role, t.ROLES)
                self.assertIn(c.expect, ("allow", "deny", "guardrail"))
                self.assertRegex(c.action, r"^[a-z0-9-]+:[A-Za-z]+$")
                self.assertTrue(c.why)
                c.resource.format(**arns)  # every placeholder is known

    def test_each_role_has_allows_denies_and_guardrails(self):
        for env in t.ROLES:
            kinds = {c.expect for c in t.CASES if c.role == env}
            self.assertEqual(kinds, {"allow", "deny", "guardrail"}, env)

    def test_validation_name_has_acms_shape(self):
        label = t.VALIDATION_NAME.split(".")[0]
        self.assertRegex(label, r"^_[0-9a-f]{32}$")

    def test_decisions(self):
        self.assertTrue(t.passes("allow", "allowed"))
        self.assertFalse(t.passes("allow", "implicitDeny"))
        self.assertTrue(t.passes("deny", "implicitDeny"))
        self.assertTrue(t.passes("deny", "explicitDeny"))
        self.assertFalse(t.passes("deny", "allowed"))
        self.assertTrue(t.passes("guardrail", "explicitDeny"))
        self.assertFalse(t.passes("guardrail", "implicitDeny"))

    def test_context_entry_types(self):
        entries = t.context_entries({"aws:TagKeys": ["Environment"], "aws:RequestTag/Environment": "qa"})
        self.assertEqual(entries, [
            {"ContextKeyName": "aws:RequestTag/Environment", "ContextKeyValues": ["qa"], "ContextKeyType": "string"},
            {"ContextKeyName": "aws:TagKeys", "ContextKeyValues": ["Environment"], "ContextKeyType": "stringList"},
        ])


class FakeAws:
    """Answers the CLI calls run_checks makes. The simulator answers what each case expects,
    unless the case's reason is in wrong."""

    def __init__(self, wrong=(), findings=(), attached=()):
        self.wrong = set(wrong)
        self.findings = list(findings)
        self.attached = list(attached)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        cmd = tuple(args[:2])
        if cmd == ("sts", "get-caller-identity"):
            return {"Account": ACCOUNT}
        if cmd == ("route53", "list-hosted-zones-by-name"):
            return {"HostedZones": [{"Id": f"/hostedzone/{ZONE}", "Name": f"{t.QA_DOMAIN}."},
                                    {"Id": "/hostedzone/ZOTHER", "Name": f"x{t.QA_DOMAIN}."}]}
        role = args[args.index("--role-name") + 1] if "--role-name" in args else None
        env = {v: k for k, v in t.ROLES.items()}.get(role)
        if cmd == ("iam", "get-role"):
            self.env = env  # run_checks reads a role, then simulates its cases
            return {"Role": {"AssumeRolePolicyDocument": trust(env)}}
        if cmd == ("iam", "list-role-policies"):
            return {"PolicyNames": ["access", "guardrails"]}
        if cmd == ("iam", "get-role-policy"):
            return {"PolicyDocument": {"Version": "2012-10-17", "Statement": []}}
        if cmd == ("iam", "list-attached-role-policies"):
            return {"AttachedPolicies": [{"PolicyName": n} for n in self.attached]}
        if cmd == ("accessanalyzer", "validate-policy"):
            return {"findings": self.findings}
        if cmd == ("iam", "simulate-custom-policy"):
            request = json.loads(args[args.index("--cli-input-json") + 1])
            case = next(c for c in t.CASES
                        if c.role == self.env and c.action == request["ActionNames"][0]
                        and t.context_entries(c.context) == request["ContextEntries"]
                        and c.resource.format(**t.resources(ACCOUNT, ZONE)) == request["ResourceArns"][0])
            decision = {"allow": "allowed", "deny": "implicitDeny", "guardrail": "explicitDeny"}[case.expect]
            if case.why in self.wrong:
                decision = "allowed" if case.expect != "allow" else "implicitDeny"
            return {"EvaluationResults": [{"EvalDecision": decision}]}
        raise AssertionError(f"unexpected call {args}")


def run(aws):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch.object(t, "cli", lambda profile: aws):
        code = t.main([])
    return code, out.getvalue()


class Report(unittest.TestCase):
    def test_all_pass(self):
        aws = FakeAws()
        code, out = run(aws)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        # Every case ran once, against the zone named exactly qa.<domain>.
        sims = [a for a in aws.calls if a[:2] == ["iam", "simulate-custom-policy"]]
        self.assertEqual(len(sims), len(t.CASES))
        self.assertTrue(all(f"hostedzone/{ZONE}" in a[-1] or "hostedzone" not in a[-1] for a in sims))

    def test_output_names_no_account(self):
        _, out = run(FakeAws())
        self.assertNotIn(ACCOUNT, out)

    def test_a_wrong_decision_fails(self):
        code, out = run(FakeAws(wrong={"delete the production bucket"}))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL  production  guardrail .*delete the production bucket -> allowed")

    def test_a_security_warning_fails_but_a_suggestion_doesnt(self):
        code, _ = run(FakeAws(findings=[{"findingType": "SUGGESTION", "issueCode": "EMPTY_ARRAY_ACTION"}]))
        self.assertEqual(code, 0)
        code, out = run(FakeAws(findings=[{"findingType": "SECURITY_WARNING", "issueCode": "PASS_ROLE_WITH_STAR"}]))
        self.assertEqual(code, 1)
        self.assertIn("SECURITY_WARNING PASS_ROLE_WITH_STAR", out)

    def test_an_attached_managed_policy_fails(self):
        code, out = run(FakeAws(attached=["AdministratorAccess"]))
        self.assertEqual(code, 1)
        self.assertIn("attached: AdministratorAccess", out)

    def test_an_aws_error_exits_2(self):
        def broken(args):
            raise RuntimeError("aws sts get-caller-identity failed: token expired")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = run(broken)
        self.assertEqual(code, 2)
        self.assertIn("token expired", err.getvalue())


if __name__ == "__main__":
    unittest.main()
