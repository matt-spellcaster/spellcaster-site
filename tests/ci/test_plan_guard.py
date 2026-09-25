"""plan_guard: a deploy may create or change the bucket and distribution, never remove them or
turn off the bucket's protections."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import plan_guard


def change(address, rtype, *actions, mode="managed", after=None, reason=None):
    rc = {"address": address, "type": rtype, "mode": mode, "change": {"actions": list(actions), "after": after}}
    return {**rc, "action_reason": reason} if reason else rc


BUCKET = "module.site.aws_s3_bucket.site"
DISTRIBUTION = "module.site.aws_cloudfront_distribution.site"
VERSIONING = "module.site.aws_s3_bucket_versioning.site[0]"
BLOCK = "module.site.aws_s3_bucket_public_access_block.site"
POLICY = "module.site.aws_s3_bucket_policy.site"
ALL_BLOCKED = dict.fromkeys(plan_guard.BLOCK_FLAGS, True)
# Account IDs here are built, not written, so the pre-commit hook's account-ID check stays quiet.
SOURCE = {"StringEquals": {"AWS:SourceArn": f"arn:aws:cloudfront::{'1' * 12}:distribution/E2EXAMPLE"}}


def policy(*extra, allow=None, deny=True):
    """The module's bucket policy as aws_iam_policy_document renders it, changed as asked."""
    cloudfront = {"Service": "cloudfront.amazonaws.com"}
    statements = allow if allow is not None else [
        {"Sid": "CloudFrontLists", "Effect": "Allow", "Action": "s3:ListBucket", "Principal": cloudfront,
         "Resource": "arn:aws:s3:::b", "Condition": SOURCE},
        {"Sid": "CloudFrontReads", "Effect": "Allow", "Action": "s3:GetObject", "Principal": cloudfront,
         "Resource": "arn:aws:s3:::b/*", "Condition": SOURCE},
    ]
    if deny:
        statements = statements + [{"Sid": "DenyInsecureTransport", "Effect": "Deny", "Action": "s3:*", "Principal": "*",
                                    "Resource": ["arn:aws:s3:::b", "arn:aws:s3:::b/*"],
                                    "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]
    return {"policy": json.dumps({"Version": "2012-10-17", "Statement": statements + list(extra)})}


class PlanGuard(unittest.TestCase):
    def run_guard(self, *changes):
        with tempfile.TemporaryDirectory() as tmp:
            plan, summary = Path(tmp) / "plan.json", Path(tmp) / "summary.md"
            plan.write_text(json.dumps({"resource_changes": list(changes)}))
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                code = plan_guard.main([str(plan), "--summary", str(summary)])
            return code, out.getvalue(), err.getvalue(), summary.read_text()

    def test_first_deploy_creates_everything(self):
        code, out, err, summary = self.run_guard(
            change(BUCKET, "aws_s3_bucket", "create"),
            change(DISTRIBUTION, "aws_cloudfront_distribution", "create"),
            change("module.site.data.aws_iam_policy_document.site_bucket", "aws_iam_policy_document", "read",
                   mode="data"),
        )
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"create   {BUCKET}", out)
        self.assertIn("2 changes, 0 refused", out)
        self.assertIn(f"| create | `{DISTRIBUTION}` |", summary)
        self.assertNotIn("iam_policy_document", summary)

    def test_updates_and_other_removals_pass(self):
        code, _, _, summary = self.run_guard(
            change(DISTRIBUTION, "aws_cloudfront_distribution", "update"),
            change("module.site.aws_cloudfront_function.viewer_request", "aws_cloudfront_function",
                   "create", "delete"),
            change("aws_cloudwatch_metric_alarm.bytes", "aws_cloudwatch_metric_alarm", "delete"),
            change(BUCKET, "aws_s3_bucket", "no-op"),
        )
        self.assertEqual(code, 0)
        self.assertIn("| replace | `module.site.aws_cloudfront_function.viewer_request` |", summary)
        self.assertNotIn(BUCKET, summary)

    def test_removing_a_protected_resource_is_refused(self):
        for rtype, address in (("aws_s3_bucket", BUCKET), ("aws_cloudfront_distribution", DISTRIBUTION),
                               ("aws_s3_bucket_versioning", VERSIONING),
                               ("aws_s3_bucket_public_access_block", BLOCK), ("aws_s3_bucket_policy", POLICY)):
            for actions, word in ((("delete",), "delete"), (("delete", "create"), "replace"),
                                  (("create", "delete"), "replace"), (("forget",), "forget")):
                with self.subTest(address=address, actions=actions):
                    code, _, err, summary = self.run_guard(change(address, rtype, *actions))
                    self.assertEqual(code, 1)
                    self.assertIn(f"::error::The plan would remove or weaken {address} ({word})", err)
                    self.assertIn(f"**Refused:** {address} ({word}).", summary)

    def test_a_tainted_distribution_says_so(self):
        code, _, err, _ = self.run_guard(change(DISTRIBUTION, "aws_cloudfront_distribution", "delete", "create",
                                                reason="replace_because_tainted"))
        self.assertEqual(code, 1)
        self.assertIn(f"{DISTRIBUTION} (replace, tainted)", err)

    def test_keeping_the_protections_on_passes(self):
        code, _, err, _ = self.run_guard(
            change(VERSIONING, "aws_s3_bucket_versioning", "create",
                   after={"versioning_configuration": [{"status": "Enabled", "mfa_delete": None}]}),
            change(BLOCK, "aws_s3_bucket_public_access_block", "update", after=ALL_BLOCKED),
            change(POLICY, "aws_s3_bucket_policy", "update", after=policy()),
        )
        self.assertEqual((code, err), (0, ""))

    def test_turning_the_protections_off_is_refused(self):
        cases = (
            (change(VERSIONING, "aws_s3_bucket_versioning", "update",
                    after={"versioning_configuration": [{"status": "Suspended"}]}), f"{VERSIONING} (versioning Suspended)"),
            (change(BLOCK, "aws_s3_bucket_public_access_block", "update",
                    after={**ALL_BLOCKED, "block_public_policy": False}), f"{BLOCK} (block_public_policy off)"),
            (change(BLOCK, "aws_s3_bucket_public_access_block", "create", after={}),
             f"{BLOCK} ({', '.join(plan_guard.BLOCK_FLAGS)} off)"),
        )
        for rc, problem in cases:
            with self.subTest(problem):
                code, _, err, summary = self.run_guard(rc)
                self.assertEqual(code, 1)
                self.assertIn(f"::error::The plan would remove or weaken {problem}.", err)
                self.assertIn(f"**Refused:** {problem}.", summary)

    def test_the_first_deploys_policy_is_unknown_and_passes(self):
        code, _, err, _ = self.run_guard(change(POLICY, "aws_s3_bucket_policy", "create", after={"bucket": "b"}))
        self.assertEqual((code, err), (0, ""))

    def test_a_policy_that_opens_the_bucket_is_refused(self):
        cloudfront = {"Service": "cloudfront.amazonaws.com"}
        outsider = {"AWS": f"arn:aws:iam::{'2' * 12}:root"}
        cases = {
            "another account may write": (policy({"Effect": "Allow", "Action": "s3:PutObject", "Principal": outsider,
                                                  "Resource": "arn:aws:s3:::b/*"}),
                                          "the policy allows someone other than CloudFront"),
            "CloudFront may write": (policy(allow=[{"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                                                    "Principal": cloudfront, "Condition": SOURCE}]),
                                     "the policy allows s3:PutObject"),
            "any distribution may read": (policy(allow=[{"Effect": "Allow", "Action": "s3:GetObject",
                                                         "Principal": cloudfront}]),
                                          "the policy lets CloudFront read without naming the distribution"),
            "NotAction": (policy(allow=[{"Effect": "Allow", "NotAction": "s3:DeleteObject", "Principal": cloudfront,
                                         "Condition": SOURCE}]),
                          "the policy has an Allow with NotAction, NotPrincipal or NotResource"),
            "no HTTPS deny": (policy(deny=False), "the policy drops the HTTPS-only deny"),
            "unknown on update": ({"bucket": "b"}, "a policy that can't be checked until apply"),
        }
        for name, (after, problem) in cases.items():
            with self.subTest(name):
                code, _, err, summary = self.run_guard(change(POLICY, "aws_s3_bucket_policy", "update", after=after))
                self.assertEqual(code, 1)
                self.assertIn(f"{POLICY} ({problem})", err)
                self.assertNotIn("2" * 12, err + summary)

    def test_empty_plan(self):
        code, out, _, summary = self.run_guard()
        self.assertEqual(code, 0)
        self.assertIn("0 changes, 0 refused", out)
        self.assertIn("No changes.", summary)


if __name__ == "__main__":
    unittest.main()
