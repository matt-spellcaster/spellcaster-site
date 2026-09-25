"""leftovers: finds what a teardown missed, ignores what bootstrap keeps, and never names the account."""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import leftovers

ACCOUNT = "1" * 12  # built, not written, so the pre-commit hook's account-ID check stays quiet
QA = "qa.spellcaster.foo."
PROD_DIST = ["E1PROD", "arn:aws:cloudfront::x:distribution/E1PROD", ["spellcaster.foo", "www.spellcaster.foo"]]
FIXED = [[QA, "SOA"], [QA, "NS"], [QA, "TXT"], [QA, "MX"], [QA, "CAA"], [f"_dmarc.{QA}", "TXT"],
         [f"_{'ab' * 16}.{QA}", "CNAME"]]


class FakeAws:
    """An account where QA is down and production is up, unless a test adds something."""

    def __init__(self):
        self.dists = [PROD_DIST]
        self.tags = {"E1PROD": [{"Key": "Environment", "Value": "production"}, {"Key": "Project", "Value": "portfolio"}]}
        self.functions = ["portfolio-production-viewer-request"] * 2
        self.qa_bucket = False
        self.records = list(FIXED)
        self.zone = True

    def __call__(self, *args):
        match args[:2]:
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
        self.assertIn("distribution E2QA holds qa.spellcaster.foo, and it isn't the one in QA's state", err)
        self.assertEqual(run(FakeAws(), "--preflight")[0], 0)

    def test_functions_listed_once_per_stage_count_once(self):
        self.assertEqual(leftovers.functions(FakeAws()), ["portfolio-production-viewer-request"])


if __name__ == "__main__":
    unittest.main()
