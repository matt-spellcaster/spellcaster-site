"""plan_guard: a deploy may create or change the bucket and distribution, never remove them."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import plan_guard


def change(address, rtype, *actions, mode="managed"):
    return {"address": address, "type": rtype, "mode": mode, "change": {"actions": list(actions)}}


BUCKET = "module.site.aws_s3_bucket.site"
DISTRIBUTION = "module.site.aws_cloudfront_distribution.site"


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

    def test_removing_the_bucket_or_distribution_is_refused(self):
        for rtype, address in (("aws_s3_bucket", BUCKET), ("aws_cloudfront_distribution", DISTRIBUTION)):
            for actions, word in ((("delete",), "delete"), (("delete", "create"), "replace"),
                                  (("create", "delete"), "replace"), (("forget",), "forget")):
                with self.subTest(address=address, actions=actions):
                    code, _, err, summary = self.run_guard(change(address, rtype, *actions))
                    self.assertEqual(code, 1)
                    self.assertIn(f"::error::The plan would remove {address} ({word})", err)
                    self.assertIn(f"**Refused:** {address} ({word}).", summary)

    def test_empty_plan(self):
        code, out, _, summary = self.run_guard()
        self.assertEqual(code, 0)
        self.assertIn("0 changes, 0 refused", out)
        self.assertIn("No changes.", summary)


if __name__ == "__main__":
    unittest.main()
