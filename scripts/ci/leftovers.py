"""List what a teardown left behind in AWS. It only reads; it never deletes anything.

    python3 scripts/ci/leftovers.py --scope qa         # after QA down (CI, as portfolio-qa)
    python3 scripts/ci/leftovers.py --scope all        # after a full teardown (docs/teardown.md)
    python3 scripts/ci/leftovers.py --preflight [--known <distribution id>]   # before QA up

--scope qa: QA's distribution (found by its name or its Environment tag), its function, its
bucket, and any record in the qa zone besides the fixed ones bootstrap made.
--scope all: anything of the site's at all. Run it on your Mac with read-only access
(AWS_PROFILE=portfolio-read), once every root is destroyed.
--preflight: fails if a distribution other than --known (the one in QA's state) holds
qa.<domain>. CloudFront would refuse the name, but only after QA up had built half a stack.

Exits 0 when nothing is left, 1 when something is (each one listed), 2 when it couldn't
check. Nothing it prints names the account. Runs the AWS CLI. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Callable

DOMAIN = "spellcaster.foo"
QA_DOMAIN = f"qa.{DOMAIN}"
PREFIX = "portfolio-"
# What bootstrap keeps in the qa zone (infra/bootstrap/dns.tf and certificate.tf).
FIXED_RECORDS = {
    (f"{QA_DOMAIN}.", "SOA"), (f"{QA_DOMAIN}.", "NS"), (f"{QA_DOMAIN}.", "TXT"), (f"{QA_DOMAIN}.", "MX"),
    (f"{QA_DOMAIN}.", "CAA"), (f"_dmarc.{QA_DOMAIN}.", "TXT"),
}
ACCOUNT_ID = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
VALIDATION_RECORD = re.compile(rf"_[0-9a-f]{{32}}\.{re.escape(QA_DOMAIN)}\.")

Aws = Callable[..., object]


def aws_cli(*args: str) -> object:
    done = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return json.loads(done.stdout or "null")


def distributions(aws: Aws) -> list[dict]:
    """Every distribution in the account: its ID, names and tags."""
    items = aws("cloudfront", "list-distributions", "--query", "DistributionList.Items[].[Id,ARN,Aliases.Items]") or []
    result = []
    for dist_id, arn, aliases in items:
        tags = aws("cloudfront", "list-tags-for-resource", "--resource", arn, "--query", "Tags.Items") or []
        result.append({"id": dist_id, "aliases": aliases or [], "tags": {t["Key"]: t["Value"] for t in tags}})
    return result


def functions(aws: Aws) -> list[str]:
    # Each function is listed once per stage (DEVELOPMENT and LIVE).
    return sorted(set(aws("cloudfront", "list-functions", "--query", "FunctionList.Items[].Name") or []))


def bucket_exists(aws: Aws, name: str) -> bool:
    """head-bucket needs only s3:ListBucket on that bucket, which the QA role has."""
    try:
        aws("s3api", "head-bucket", "--bucket", name)
        return True
    except RuntimeError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return False
        raise


def qa_zone_id(aws: Aws) -> str | None:
    zones = aws("route53", "list-hosted-zones-by-name", "--dns-name", QA_DOMAIN, "--max-items", "1",
                "--query", "HostedZones[].[Id,Name]") or []
    return next((zid for zid, name in zones if name == f"{QA_DOMAIN}."), None)


def extra_records(aws: Aws, zone_id: str) -> list[str]:
    records = aws("route53", "list-resource-record-sets", "--hosted-zone-id", zone_id,
                  "--query", "ResourceRecordSets[].[Name,Type]") or []
    return [f"{rtype} {name}" for name, rtype in records
            if (name, rtype) not in FIXED_RECORDS and not (rtype == "CNAME" and VALIDATION_RECORD.fullmatch(name))]


def check_qa(aws: Aws, account_id: str) -> list[str]:
    left = [f"distribution {d['id']} ({', '.join(d['aliases']) or 'no names'})" for d in distributions(aws)
            if QA_DOMAIN in d["aliases"] or d["tags"].get("Environment") == "qa"]
    left += [f"function {name}" for name in functions(aws) if name.startswith(f"{PREFIX}qa-")]
    if bucket_exists(aws, f"{PREFIX}qa-{account_id}-us-east-1-an"):
        left.append("the QA bucket")
    zone = qa_zone_id(aws)
    if zone is None:
        raise RuntimeError(f"the {QA_DOMAIN} zone is missing: bootstrap should hold it")
    left += [f"record {r}" for r in extra_records(aws, zone)]
    return left


def check_all(aws: Aws) -> list[str]:
    """After a full teardown, nothing of the site's should be left anywhere."""
    left = [f"distribution {d['id']} ({', '.join(d['aliases']) or 'no names'})" for d in distributions(aws)
            if d["tags"].get("Project") == "portfolio" or any(a == DOMAIN or a.endswith(f".{DOMAIN}")
                                                               for a in d["aliases"])]
    left += [f"function {name}" for name in functions(aws) if name.startswith(PREFIX)]
    left += [f"bucket {name}" for name in aws("s3api", "list-buckets", "--query", "Buckets[].Name") or []
             if name.startswith(PREFIX)]
    if qa_zone_id(aws):
        left.append(f"hosted zone {QA_DOMAIN}")
    left += [f"certificate {name}" for name in
             aws("acm", "list-certificates", "--query", "CertificateSummaryList[].DomainName") or []
             if name == DOMAIN or name.endswith(f".{DOMAIN}")]
    left += [f"role {name}" for name in aws("iam", "list-roles", "--query", "Roles[].RoleName") or []
             if name.startswith(PREFIX)]
    left += ["GitHub's OIDC provider" for arn in
             aws("iam", "list-open-id-connect-providers", "--query", "OpenIDConnectProviderList[].Arn") or []
             if arn.endswith("/token.actions.githubusercontent.com")]
    left += [f"origin access control {name}" for name in
             aws("cloudfront", "list-origin-access-controls", "--query", "OriginAccessControlList.Items[].Name") or []
             if name.startswith(PREFIX)]
    left += [f"response headers policy {name}" for name in
             aws("cloudfront", "list-response-headers-policies", "--type", "custom",
                 "--query", "ResponseHeadersPolicyList.Items[].ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name")
             or [] if name.startswith(PREFIX)]
    left += [f"alarm {name}" for name in
             aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", PREFIX, "--query", "MetricAlarms[].AlarmName")
             or []]
    left += [f"topic {arn.rsplit(':', 1)[1]}" for arn in
             aws("sns", "list-topics", "--query", "Topics[].TopicArn") or [] if arn.rsplit(":", 1)[1].startswith(PREFIX)]
    account_id = aws("sts", "get-caller-identity", "--query", "Account")
    left += [f"budget {name}" for name in
             aws("budgets", "describe-budgets", "--account-id", account_id, "--query", "Budgets[].BudgetName") or []
             if name.startswith(PREFIX)]
    return left


def preflight(aws: Aws, known: str | None) -> list[str]:
    return [f"distribution {d['id']} holds {QA_DOMAIN}" for d in distributions(aws)
            if QA_DOMAIN in d["aliases"] and d["id"] != known]


def masked(text: str) -> str:
    """Bucket names and ARNs contain the account ID, and CI logs are public."""
    return ACCOUNT_ID.sub("<account>", text)


def main(argv: list[str] | None = None, aws: Aws = aws_cli) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scope", choices=["qa", "all"])
    mode.add_argument("--preflight", action="store_true")
    p.add_argument("--known", help="with --preflight: the distribution in QA's state, which may hold the name")
    args = p.parse_args(argv)

    try:
        if args.preflight:
            left = preflight(aws, args.known or None)
        elif args.scope == "qa":
            account_id = aws("sts", "get-caller-identity", "--query", "Account")
            left = check_qa(aws, account_id)
        else:
            left = check_all(aws)
    except (RuntimeError, ValueError) as e:
        print(masked(f"::error::Couldn't check: {e}"), file=sys.stderr)
        return 2
    for item in left:
        print(masked(f"left: {item}"))
    if args.preflight and left:
        print(masked(f"::error::{left[0]}, and it isn't the one in QA's state. Run QA down, then docs/qa.md "
              "(\"If QA down leaves something\")."), file=sys.stderr)
    elif left:
        doc = "docs/qa.md (\"If QA down leaves something\")" if args.scope == "qa" else "docs/teardown.md"
        print(f"::error::{len(left)} left behind. {doc} says what to do.", file=sys.stderr)
    print(f"{len(left)} left behind" if not args.preflight else f"{len(left)} other distributions hold {QA_DOMAIN}")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
