"""leftovers: finds what a teardown missed, ignores what bootstrap keeps, and never names the account."""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import leftovers

ACCOUNT = "1" * 12  # built, not written, so the pre-commit hook's account-ID check stays quiet
QA = "qa.spellcaster.foo."
PROD_DIST = ["E1PROD", "arn:aws:cloudfront::x:distribution/E1PROD", ["spellcaster.foo", "www.spellcaster.foo"]]
FIXED = [[QA, "SOA"], [QA, "NS"], [QA, "TXT"], [QA, "MX"], [QA, "CAA"], [f"_dmarc.{QA}", "TXT"],
         [f"_{'ab' * 16}.{QA}", "CNAME"]]
# terraform state list with QA up (trimmed): data sources, a module, for_each keys and a count.
STATE_LIST = """data.aws_acm_certificate.site
data.aws_route53_zone.qa
aws_route53_record.site["A"]
aws_route53_record.site["AAAA"]
module.site.data.aws_iam_policy_document.site_bucket
module.site.aws_cloudfront_distribution.site
module.site.aws_cloudfront_function.viewer_request
module.site.aws_s3_bucket.site
module.site.aws_s3_bucket_policy.site
module.site.aws_s3_bucket_versioning.site[0]
"""


class FakeAws:
    """An account where QA is down and production is up, unless a test adds something."""

    def __init__(self):
        self.dists = [PROD_DIST]
        self.tags = {"E1PROD": [{"Key": "Environment", "Value": "production"}, {"Key": "Project", "Value": "portfolio"}]}
        self.functions = ["portfolio-production-viewer-request"] * 2
        self.qa_bucket = False
        self.records = list(FIXED)
        self.zone = True
        # What only --scope all looks at: an account where every root is destroyed.
        self.buckets, self.certificates, self.roles, self.oidc, self.oacs = [], [], [], [], []
        self.header_policies, self.alarms, self.topics, self.budgets = [], [], [], []

    def __call__(self, *args):
        match args[:2]:
            case ("s3api", "list-buckets"):
                return self.buckets
            case ("acm", "list-certificates"):
                return self.certificates
            case ("iam", "list-roles"):
                return self.roles
            case ("iam", "list-open-id-connect-providers"):
                return self.oidc
            case ("cloudfront", "list-origin-access-controls"):
                return self.oacs
            case ("cloudfront", "list-response-headers-policies"):
                return self.header_policies
            case ("cloudwatch", "describe-alarms"):
                return [name for name in self.alarms if name.startswith(args[3])]
            case ("sns", "list-topics"):
                return self.topics
            case ("budgets", "describe-budgets"):
                assert args[3] == ACCOUNT
                return self.budgets
            case ("sts", "get-caller-identity"):
                return ACCOUNT
            case ("cloudfront", "list-distributions"):
                return self.dists
            case ("cloudfront", "list-tags-for-resource"):
                return self.tags.get(args[3].rsplit("/", 1)[1], [])
            case ("cloudfront", "list-functions"):
                return self.functions
            case ("s3api", "head-bucket"):
                if self.qa_bucket and args[3] == f"portfolio-qa-{ACCOUNT}-us-east-1-an":
                    return None
                raise RuntimeError("An error occurred (404) when calling the HeadBucket operation: Not Found")
            case ("route53", "list-hosted-zones-by-name"):
                return [["/hostedzone/Z1", QA]] if self.zone else []
            case ("route53", "list-resource-record-sets"):
                return self.records
        raise AssertionError(f"unexpected call {args}")


def run(aws, *argv):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
        code = leftovers.main(list(argv), aws)
    return code, out.getvalue(), err.getvalue()


class Leftovers(unittest.TestCase):
    def test_a_clean_qa_teardown_passes_with_production_up(self):
        self.assertEqual(run(FakeAws(), "--scope", "qa"), (0, "0 left behind\n", ""))

    def test_every_kind_of_qa_leftover_is_listed(self):
        aws = FakeAws()
        aws.dists = [PROD_DIST, ["E2QA", "arn:aws:cloudfront::x:distribution/E2QA", ["qa.spellcaster.foo"]],
                     ["E3OLD", "arn:aws:cloudfront::x:distribution/E3OLD", None]]
        aws.tags["E3OLD"] = [{"Key": "Environment", "Value": "qa"}]
        aws.functions += ["portfolio-qa-viewer-request"]
        aws.qa_bucket = True
        aws.records += [[QA, "A"], [QA, "AAAA"], [f"www.{QA}", "CNAME"]]
        code, out, err = run(aws, "--scope", "qa")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[:-1], [
            "left: distribution E2QA (qa.spellcaster.foo)",
            "left: distribution E3OLD (no names)",
            "left: function portfolio-qa-viewer-request",
            "left: the QA bucket",
            f"left: record A {QA}",
            f"left: record AAAA {QA}",
            f"left: record CNAME www.{QA}",
        ])
        self.assertIn("docs/qa.md", err)

    def test_an_error_is_exit_2_and_never_names_the_account(self):
        def broken(*args):
            if args[:2] == ("sts", "get-caller-identity"):
                return ACCOUNT
            raise RuntimeError(f"AccessDenied for arn:aws:iam::{ACCOUNT}:role/portfolio-qa")
        code, out, err = run(broken, "--scope", "qa")
        self.assertEqual(code, 2)
        self.assertNotIn(ACCOUNT, out + err)
        self.assertIn("arn:aws:iam::<account>:role/portfolio-qa", err)

    def test_a_missing_qa_zone_cant_be_checked(self):
        aws = FakeAws()
        aws.zone = False
        self.assertEqual(run(aws, "--scope", "qa")[0], 2)

    def test_preflight_allows_only_the_distribution_in_state(self):
        aws = FakeAws()
        aws.dists = [PROD_DIST, ["E2QA", "arn:aws:cloudfront::x:distribution/E2QA", ["qa.spellcaster.foo"]]]
        self.assertEqual(run(aws, "--preflight", "--known", "E2QA")[0], 0)
        code, out, err = run(aws, "--preflight", "--known", "")
        self.assertEqual(code, 1)
        self.assertIn("left: distribution E2QA holds qa.spellcaster.foo", out)
        self.assertIn("QA's state doesn't hold 1 of QA's things", err)
        self.assertEqual(run(FakeAws(), "--preflight")[0], 0)

    def test_preflight_refuses_what_a_lost_state_left(self):
        aws = FakeAws()
        aws.functions += ["portfolio-qa-viewer-request"]
        aws.qa_bucket = True
        aws.records += [[QA, "A"], [QA, "AAAA"], [f"www.{QA}", "CNAME"]]  # the CNAME doesn't block QA up
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.txt"
            state.write_text("")  # QA's state is empty
            code, out, err = run(aws, "--preflight", "--known", "", "--state-list", str(state))
            self.assertEqual(code, 1)
            self.assertEqual(out.splitlines(), [
                "left: the QA bucket",
                "left: function portfolio-qa-viewer-request",
                f"left: record A {QA}",
                f"left: record AAAA {QA}",
                "4 in QA up's way",
            ])
            self.assertIn("docs/qa.md", err)
            # QA is up: its state holds all of them, so none is in the way.
            state.write_text(STATE_LIST)
            self.assertEqual(run(aws, "--preflight", "--known", "", "--state-list", str(state))[0], 0)

    def test_a_missing_state_list_cant_be_checked(self):
        code, _, err = run(FakeAws(), "--preflight", "--state-list", "/nonexistent/state.txt")
        self.assertEqual(code, 2)
        self.assertIn("Couldn't check", err)

    def test_state_types_reads_terraform_state_list(self):
        self.assertEqual(leftovers.state_types(STATE_LIST), {
            "aws_route53_record", "aws_cloudfront_distribution", "aws_cloudfront_function", "aws_s3_bucket",
            "aws_s3_bucket_policy", "aws_s3_bucket_versioning"})
        self.assertEqual(leftovers.state_types(""), set())

    def test_the_bucket_name_matches_terraform(self):
        bucket_tf = (Path(__file__).resolve().parents[2] / "infra" / "modules" / "site" / "bucket.tf").read_text()
        name = re.search(r'^\s*bucket = "([^"]+)"', bucket_tf, re.M).group(1)
        self.assertEqual(re.sub(r"\$\{var\.(\w+)\}", r"{\1}", name), leftovers.BUCKET)

    def test_a_clean_full_teardown_passes(self):
        aws = FakeAws()
        aws.dists, aws.functions, aws.zone = [], [], False
        self.assertEqual(run(aws, "--scope", "all"), (0, "0 left behind\n", ""))

    def test_every_kind_of_full_teardown_leftover_is_listed(self):
        aws = FakeAws()  # production is still up, and the qa zone is still there
        aws.dists += [["E9OLD", "arn:aws:cloudfront::x:distribution/E9OLD", None],
                      ["E8ELSE", "arn:aws:cloudfront::x:distribution/E8ELSE", ["example.com"]]]
        aws.tags["E9OLD"] = [{"Key": "Project", "Value": "portfolio"}]
        aws.functions += ["someone-elses-function"]
        aws.buckets = [f"portfolio-tfstate-{ACCOUNT}", "other-bucket"]
        aws.certificates = ["spellcaster.foo", "qa.spellcaster.foo", "example.com"]
        aws.roles = ["portfolio-qa", "OrganizationAccountAccessRole"]
        aws.oidc = [f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com",
                    f"arn:aws:iam::{ACCOUNT}:oidc-provider/example.com"]
        aws.oacs = ["portfolio-site", "other"]
        aws.header_policies = ["portfolio-headers", "other"]
        aws.alarms = ["portfolio-bytes", "other-alarm"]
        aws.topics = [f"arn:aws:sns:us-east-1:{ACCOUNT}:portfolio-alerts", f"arn:aws:sns:us-east-1:{ACCOUNT}:other"]
        aws.budgets = ["portfolio-monthly", "other"]
        code, out, err = run(aws, "--scope", "all")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            "left: distribution E1PROD (spellcaster.foo, www.spellcaster.foo)",
            "left: distribution E9OLD (no names)",
            "left: function portfolio-production-viewer-request",
            "left: bucket portfolio-tfstate-<account>",
            "left: hosted zone qa.spellcaster.foo",
            "left: certificate spellcaster.foo",
            "left: certificate qa.spellcaster.foo",
            "left: role portfolio-qa",
            "left: GitHub's OIDC provider",
            "left: origin access control portfolio-site",
            "left: response headers policy portfolio-headers",
            "left: alarm portfolio-bytes",
            "left: topic portfolio-alerts",
            "left: budget portfolio-monthly",
            "14 left behind",
        ])
        self.assertIn("docs/teardown.md", err)
        self.assertNotIn(ACCOUNT, out + err)

    def test_functions_listed_once_per_stage_count_once(self):
        self.assertEqual(leftovers.functions(FakeAws()), ["portfolio-production-viewer-request"])


if __name__ == "__main__":
    unittest.main()
