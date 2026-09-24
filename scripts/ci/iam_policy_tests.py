"""Check what the CI roles may and may not do in AWS.

Reads the live portfolio-qa and portfolio-prod roles, then:
  1. checks each trust policy: GitHub's OIDC provider, the sts.amazonaws.com audience, and
     only this repository's own environment, matched by its owner and repository IDs;
  2. checks the roles have inline policies only, no managed policies attached;
  3. validates every policy with IAM Access Analyzer (errors and security warnings fail);
  4. runs each case in CASES through the IAM policy simulator, with the request's tags,
     certificate names and DNS record names as context, and compares the decision.

Run it on your Mac after applying infra/bootstrap. Read-only access is enough:

    python3 -I scripts/ci/iam_policy_tests.py --profile portfolio-read

It needs the AWS CLI. Exit codes: 0 every check passed, 1 a check failed, 2 it couldn't run.
Nothing it prints or writes names the account: resources are shown as {placeholders}.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# The same values as infra/bootstrap's variables (tests/ci checks they agree).
DOMAIN = "spellcaster.foo"
QA_DOMAIN = f"qa.{DOMAIN}"
OWNER = "matt-spellcaster"
OWNER_ID = 329836411
REPO_ID = 1384189986
REGION = "us-east-1"
OIDC_HOST = "token.actions.githubusercontent.com"
TAG_KEYS = ["Project", "Environment", "ManagedBy", "Repository"]
ROLES = {"qa": "portfolio-qa", "production": "portfolio-prod"}
# ACM's validation record names: an underscore and 32 hex characters.
VALIDATION_NAME = f"_{'0123456789abcdef' * 2}.{QA_DOMAIN}"

Aws = Callable[[list[str]], dict]


@dataclass(frozen=True)
class Case:
    """One request, and what the role's policies should decide.

    expect is "allow", "deny" (not allowed, by any means) or "guardrail" (an explicit deny,
    so no future allow can open it up).
    """

    role: str
    expect: str
    action: str
    resource: str
    why: str
    context: dict[str, str | list[str]] = field(default_factory=dict)


def tagged(env: str) -> dict[str, str]:
    """An existing resource with this Environment tag."""
    return {"aws:ResourceTag/Environment": env}


def new_tags(env: str, keys: list[str] | None = None) -> dict[str, str | list[str]]:
    """A request that sets these tags (the four standard keys unless given)."""
    return {"aws:RequestTag/Environment": env, "aws:TagKeys": keys or TAG_KEYS}


def records(types: list[str], names: list[str]) -> dict[str, list[str]]:
    return {
        "route53:ChangeResourceRecordSetsRecordTypes": types,
        "route53:ChangeResourceRecordSetsNormalizedRecordNames": names,
        "route53:ChangeResourceRecordSetsActions": ["UPSERT"],
    }


def certificate_request(domains: list[str], method: str = "DNS", export: str = "DISABLED"):
    return {"acm:DomainNames": domains, "acm:ValidationMethod": method, "acm:Export": export,
            **new_tags("qa")}


def _cases() -> list[Case]:
    qa, prod = "qa", "production"
    c = Case
    return [
        # --- Terraform state: each role its own key --------------------------------------
        c(qa, "allow", "s3:ListBucket", "{state}", "list the state bucket"),
        c(qa, "allow", "s3:PutObject", "{state}/envs/qa/terraform.tfstate", "write QA state"),
        c(qa, "allow", "s3:DeleteObject", "{state}/envs/qa/terraform.tfstate.tflock", "release the QA lock"),
        c(qa, "deny", "s3:GetObject", "{state}/envs/prod/terraform.tfstate", "read production state"),
        c(qa, "deny", "s3:GetObject", "{state}/bootstrap/terraform.tfstate", "read bootstrap state"),
        c(qa, "deny", "s3:DeleteObject", "{state}/envs/qa/terraform.tfstate", "delete QA state"),
        c(qa, "deny", "s3:PutBucketPolicy", "{state}", "change the state bucket"),
        c(prod, "allow", "s3:PutObject", "{state}/envs/prod/terraform.tfstate", "write production state"),
        c(prod, "allow", "s3:PutObject", "{state}/envs/prod/terraform.tfstate.tflock", "take the production lock"),
        c(prod, "deny", "s3:GetObject", "{state}/envs/qa/terraform.tfstate", "read QA state"),
        c(prod, "deny", "s3:GetObject", "{state}/bootstrap/terraform.tfstate", "read bootstrap state"),
        # --- Site buckets: by name ------------------------------------------------------
        c(qa, "allow", "s3:CreateBucket", "{qa_bucket}", "create the QA bucket"),
        c(qa, "allow", "s3:PutBucketPolicy", "{qa_bucket}", "let CloudFront read the QA bucket"),
        c(qa, "allow", "s3:PutObject", "{qa_bucket}/index.html", "publish to QA"),
        c(qa, "allow", "s3:DeleteObjectVersion", "{qa_bucket}/index.html", "empty the QA bucket"),
        c(qa, "allow", "s3:DeleteBucket", "{qa_bucket}", "tear QA down"),
        c(qa, "deny", "s3:PutObject", "{prod_bucket}/index.html", "publish to production"),
        c(qa, "deny", "s3:PutBucketPolicy", "{prod_bucket}", "change production's bucket policy"),
        c(qa, "guardrail", "s3:PutAccountPublicAccessBlock", "*", "turn off the account's public-access block"),
        c(prod, "allow", "s3:CreateBucket", "{prod_bucket}", "create the production bucket"),
        c(prod, "allow", "s3:PutObject", "{prod_bucket}/index.html", "publish to production"),
        c(prod, "allow", "s3:DeleteObject", "{prod_bucket}/_astro/old.js", "prune old files"),
        c(prod, "guardrail", "s3:DeleteBucket", "{prod_bucket}", "delete the production bucket"),
        c(prod, "guardrail", "s3:DeleteObjectVersion", "{prod_bucket}/index.html", "erase production's history"),
        c(prod, "deny", "s3:PutObject", "{qa_bucket}/index.html", "publish to QA"),
        # --- CloudFront: by the Environment tag --------------------------------------------
        c(qa, "allow", "cloudfront:CreateDistribution", "*", "create a QA distribution", new_tags(qa)),
        c(qa, "allow", "cloudfront:TagResource", "{distribution}", "tag the new QA distribution", new_tags(qa)),
        c(qa, "allow", "cloudfront:CreateFunction", "*", "create the QA function", new_tags(qa)),
        c(qa, "allow", "cloudfront:UpdateDistribution", "{distribution}", "change the QA distribution", tagged(qa)),
        c(qa, "allow", "cloudfront:DeleteDistribution", "{distribution}", "delete the QA distribution", tagged(qa)),
        c(qa, "allow", "cloudfront:CreateInvalidation", "{distribution}", "invalidate QA's cache", tagged(qa)),
        c(qa, "allow", "cloudfront:PublishFunction", "{function}", "publish the QA function", tagged(qa)),
        c(qa, "allow", "cloudfront:GetDistributionConfig", "{distribution}", "read any distribution", tagged(prod)),
        c(qa, "deny", "cloudfront:CreateDistribution", "*", "create an untagged distribution"),
        c(qa, "deny", "cloudfront:CreateDistribution", "*", "create a production distribution", new_tags(prod)),
        c(qa, "deny", "cloudfront:CreateDistribution", "*", "add a tag key outside the four",
          new_tags(qa, TAG_KEYS + ["Owner"])),
        c(qa, "deny", "cloudfront:UpdateDistribution", "{distribution}", "change production's distribution",
          tagged(prod)),
        c(qa, "deny", "cloudfront:DeleteDistribution", "{distribution}", "delete production's distribution",
          tagged(prod)),
        c(qa, "deny", "cloudfront:CreateInvalidation", "{distribution}", "invalidate production's cache",
          tagged(prod)),
        c(qa, "deny", "cloudfront:UpdateFunction", "{function}", "change production's function", tagged(prod)),
        c(qa, "guardrail", "cloudfront:TagResource", "{distribution}", "re-tag production's distribution as QA",
          {**tagged(prod), **new_tags(qa, ["Environment"])}),
        c(qa, "guardrail", "cloudfront:UntagResource", "{distribution}", "drop the Environment tag",
          {**tagged(qa), "aws:TagKeys": ["Environment"]}),
        c(qa, "guardrail", "cloudfront:AssociateAlias", "{distribution}", "move a domain onto QA", tagged(qa)),
        c(qa, "guardrail", "cloudfront:UpdateDomainAssociation", "{distribution}", "move a domain onto QA",
          tagged(qa)),
        c(qa, "guardrail", "cloudfront:UpdateResponseHeadersPolicy", "*", "weaken the security headers"),
        c(qa, "guardrail", "cloudfront:UpdateOriginAccessControl", "*", "change how CloudFront signs"),
        c(prod, "allow", "cloudfront:CreateDistribution", "*", "create the production distribution",
          new_tags(prod)),
        c(prod, "allow", "cloudfront:UpdateDistribution", "{distribution}", "change the production distribution",
          tagged(prod)),
        c(prod, "allow", "cloudfront:CreateInvalidation", "{distribution}", "invalidate production's cache",
          tagged(prod)),
        c(prod, "guardrail", "cloudfront:DeleteDistribution", "{distribution}", "delete the production distribution",
          tagged(prod)),
        c(prod, "deny", "cloudfront:UpdateDistribution", "{distribution}", "change QA's distribution", tagged(qa)),
        c(prod, "deny", "cloudfront:CreateDistribution", "*", "create a QA distribution", new_tags(qa)),
        c(prod, "guardrail", "cloudfront:TagResource", "{distribution}", "re-tag QA's distribution as production",
          {**tagged(qa), **new_tags(prod, ["Environment"])}),
        c(prod, "guardrail", "cloudfront:AssociateAlias", "{distribution}", "move a domain", tagged(prod)),
        c(prod, "guardrail", "cloudfront:UpdateResponseHeadersPolicy", "*", "weaken the security headers"),
        # --- Certificates ----------------------------------------------------------------
        c(qa, "allow", "acm:RequestCertificate", "*", "request the QA certificate", certificate_request([QA_DOMAIN])),
        c(qa, "allow", "acm:AddTagsToCertificate", "{certificate}", "tag the new QA certificate", new_tags(qa)),
        c(qa, "allow", "acm:DeleteCertificate", "{certificate}", "delete the QA certificate", tagged(qa)),
        c(qa, "allow", "acm:DescribeCertificate", "{certificate}", "read a certificate", tagged(prod)),
        c(qa, "deny", "acm:RequestCertificate", "*", "a certificate for the apex", certificate_request([DOMAIN])),
        c(qa, "deny", "acm:RequestCertificate", "*", "a certificate that adds the apex",
          certificate_request([QA_DOMAIN, DOMAIN])),
        c(qa, "deny", "acm:RequestCertificate", "*", "a certificate validated by email",
          certificate_request([QA_DOMAIN], method="EMAIL")),
        c(qa, "guardrail", "acm:RequestCertificate", "*", "an exportable certificate",
          certificate_request([QA_DOMAIN], export="ENABLED")),
        c(qa, "guardrail", "acm:ExportCertificate", "{certificate}", "export a private key", tagged(qa)),
        c(qa, "deny", "acm:DeleteCertificate", "{certificate}", "delete the production certificate", tagged(prod)),
        c(qa, "guardrail", "acm:AddTagsToCertificate", "{certificate}", "re-tag the production certificate",
          {**tagged(prod), **new_tags(qa, ["Environment"])}),
        c(prod, "allow", "acm:DescribeCertificate", "{certificate}", "wait for the certificate", tagged(prod)),
        c(prod, "guardrail", "acm:RequestCertificate", "*", "request a certificate",
          {"acm:DomainNames": [DOMAIN], "acm:ValidationMethod": "DNS", **new_tags(prod)}),
        c(prod, "guardrail", "acm:DeleteCertificate", "{certificate}", "delete the production certificate",
          tagged(prod)),
        # --- DNS (the qa zone) -------------------------------------------------------------
        c(qa, "allow", "route53:ChangeResourceRecordSets", "{zone}", "point qa at CloudFront (A)",
          records(["A"], [QA_DOMAIN])),
        c(qa, "allow", "route53:ChangeResourceRecordSets", "{zone}", "point qa at CloudFront (AAAA)",
          records(["AAAA"], [QA_DOMAIN])),
        c(qa, "allow", "route53:ChangeResourceRecordSets", "{zone}", "add ACM's validation record",
          records(["CNAME"], [VALIDATION_NAME])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "change the DMARC record",
          records(["TXT"], [f"_dmarc.{QA_DOMAIN}"])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "change the null MX",
          records(["MX"], [QA_DOMAIN])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "change the CAA record",
          records(["CAA"], [QA_DOMAIN])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "change the zone's NS records",
          records(["NS"], [QA_DOMAIN])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "add a name below qa",
          records(["A"], [f"www.{QA_DOMAIN}"])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "a CNAME at qa itself",
          records(["CNAME"], [QA_DOMAIN])),
        c(qa, "deny", "route53:ChangeResourceRecordSets", "{zone}", "a CNAME that isn't ACM's shape",
          records(["CNAME"], [f"_short.{QA_DOMAIN}"])),
        c(qa, "guardrail", "route53:DeleteHostedZone", "{zone}", "delete the qa zone"),
        c(qa, "guardrail", "route53:CreateHostedZone", "*", "create a hosted zone"),
        c(prod, "guardrail", "route53:ChangeResourceRecordSets", "{zone}", "change any DNS record",
          records(["A"], [QA_DOMAIN])),
        # --- Secrets, alarms, identity and billing ------------------------------------------
        c(qa, "allow", "ssm:GetParameter", "{password}", "read the QA password"),
        c(qa, "deny", "ssm:GetParameter", "{other_parameter}", "read another parameter"),
        c(prod, "deny", "ssm:GetParameter", "{password}", "read the QA password"),
        c(prod, "allow", "cloudwatch:PutMetricAlarm", "{prod_alarm}", "set a traffic alarm"),
        c(prod, "deny", "cloudwatch:PutMetricAlarm", "{qa_alarm}", "set an alarm outside its name prefix"),
        c(qa, "deny", "cloudwatch:PutMetricAlarm", "{prod_alarm}", "set production's alarms"),
        c(qa, "guardrail", "iam:PassRole", "{role}", "hand a role to a service"),
        c(qa, "guardrail", "iam:CreateRole", "*", "create a role"),
        c(prod, "guardrail", "iam:UpdateAssumeRolePolicy", "{role}", "widen its own trust"),
        c(prod, "guardrail", "organizations:LeaveOrganization", "*", "leave the organization"),
        c(prod, "guardrail", "budgets:ModifyBudget", "*", "change the budget"),
        c(qa, "deny", "sns:Publish", "*", "send alerts"),
    ]


CASES = _cases()


def resources(account: str, zone_id: str) -> dict[str, str]:
    """The real ARNs behind each {placeholder} in CASES."""
    suffix = f"{account}-{REGION}-an"
    return {
        "state": f"arn:aws:s3:::portfolio-tfstate-{suffix}",
        "qa_bucket": f"arn:aws:s3:::portfolio-qa-{suffix}",
        "prod_bucket": f"arn:aws:s3:::portfolio-production-{suffix}",
        "distribution": f"arn:aws:cloudfront::{account}:distribution/E0EXAMPLE",
        "function": f"arn:aws:cloudfront::{account}:function/portfolio-example",
        "certificate": f"arn:aws:acm:{REGION}:{account}:certificate/example",
        "zone": f"arn:aws:route53:::hostedzone/{zone_id}",
        "password": f"arn:aws:ssm:{REGION}:{account}:parameter/portfolio/qa/basic-auth-password",
        "other_parameter": f"arn:aws:ssm:{REGION}:{account}:parameter/portfolio/other",
        "prod_alarm": f"arn:aws:cloudwatch:{REGION}:{account}:alarm:portfolio-production-requests",
        "qa_alarm": f"arn:aws:cloudwatch:{REGION}:{account}:alarm:portfolio-qa-requests",
        "role": f"arn:aws:iam::{account}:role/portfolio-prod",
    }


def subject(env: str) -> str:
    return f"repo:{OWNER}@{OWNER_ID}/*@{REPO_ID}:environment:{env}"


def check_trust(doc: dict, env: str, account: str) -> list[str]:
    """Problems with a role's trust policy (an empty list means it's right)."""
    statements = doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if len(statements) != 1:
        return [f"expected exactly one trust statement, found {len(statements)}"]
    s = statements[0]
    problems = []
    if s.get("Effect") != "Allow":
        problems.append("the trust statement isn't an Allow")
    if s.get("Action") not in ("sts:AssumeRoleWithWebIdentity", ["sts:AssumeRoleWithWebIdentity"]):
        problems.append(f"trusted action is {s.get('Action')!r}, not only sts:AssumeRoleWithWebIdentity")
    provider = f"arn:aws:iam::{account}:oidc-provider/{OIDC_HOST}"
    if s.get("Principal") != {"Federated": provider}:
        problems.append("the principal isn't only GitHub's OIDC provider in this account")
    expected = {
        "StringEquals": {f"{OIDC_HOST}:aud": "sts.amazonaws.com"},
        "StringLike": {f"{OIDC_HOST}:sub": subject(env)},
    }
    condition = {op: {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in keys.items()}
                 for op, keys in s.get("Condition", {}).items()}
    if condition != expected:
        problems.append(f"conditions are {json.dumps(s.get('Condition'))}, expected {json.dumps(expected)}")
    return problems


def context_entries(context: dict[str, str | list[str]]) -> list[dict]:
    return [{"ContextKeyName": k,
             "ContextKeyValues": v if isinstance(v, list) else [v],
             "ContextKeyType": "stringList" if isinstance(v, list) else "string"}
            for k, v in sorted(context.items())]


def simulate(aws: Aws, policies: list[dict], case: Case, arns: dict[str, str]) -> str:
    """The simulator's decision: allowed, explicitDeny or implicitDeny."""
    request = {
        "PolicyInputList": [json.dumps(p) for p in policies],
        "ActionNames": [case.action],
        "ResourceArns": [case.resource.format(**arns)],
        "ContextEntries": context_entries(case.context),
    }
    out = aws(["iam", "simulate-custom-policy", "--cli-input-json", json.dumps(request)])
    return out["EvaluationResults"][0]["EvalDecision"]


def passes(expect: str, decision: str) -> bool:
    if expect == "allow":
        return decision == "allowed"
    if expect == "guardrail":
        return decision == "explicitDeny"
    return decision in ("explicitDeny", "implicitDeny")


def validate(aws: Aws, doc: dict, trust: bool) -> list[dict]:
    """Access Analyzer's findings for a policy."""
    args = ["accessanalyzer", "validate-policy", "--policy-document", json.dumps(doc)]
    if trust:
        args += ["--policy-type", "RESOURCE_POLICY",
                 "--validate-policy-resource-type", "AWS::IAM::AssumeRolePolicyDocument"]
    else:
        args += ["--policy-type", "IDENTITY_POLICY"]
    return aws(args).get("findings", [])


def blocking(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("findingType") in ("ERROR", "SECURITY_WARNING")]


def fetch_role(aws: Aws, name: str) -> tuple[dict, dict[str, dict], list[str]]:
    """A role's trust policy, its inline policies by name, and any attached managed policies."""
    trust = aws(["iam", "get-role", "--role-name", name])["Role"]["AssumeRolePolicyDocument"]
    names = aws(["iam", "list-role-policies", "--role-name", name])["PolicyNames"]
    inline = {n: aws(["iam", "get-role-policy", "--role-name", name, "--policy-name", n])["PolicyDocument"]
              for n in names}
    attached = aws(["iam", "list-attached-role-policies", "--role-name", name])["AttachedPolicies"]
    return trust, inline, [p["PolicyName"] for p in attached]


def qa_zone_id(aws: Aws) -> str:
    zones = aws(["route53", "list-hosted-zones-by-name", "--dns-name", QA_DOMAIN])["HostedZones"]
    ids = [z["Id"].rsplit("/", 1)[-1] for z in zones if z["Name"] == f"{QA_DOMAIN}."]
    if len(ids) != 1:
        raise RuntimeError(f"expected one hosted zone named {QA_DOMAIN}, found {len(ids)}")
    return ids[0]


def cli(profile: str | None) -> Aws:
    def run(args: list[str]) -> dict:
        cmd = ["aws", *args, "--region", REGION, "--output", "json"]
        if profile:
            cmd += ["--profile", profile]
        p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "AWS_PAGER": ""})
        if p.returncode != 0:
            raise RuntimeError(f"aws {' '.join(args[:2])} failed: {p.stderr.strip()}")
        return json.loads(p.stdout or "{}")
    return run


def run_checks(aws: Aws) -> list[dict]:
    """Every check, as rows of {check, role, ok, detail}."""
    account = aws(["sts", "get-caller-identity"])["Account"]
    arns = resources(account, qa_zone_id(aws))
    rows = []
    for env, name in ROLES.items():
        trust, inline, attached = fetch_role(aws, name)
        problems = check_trust(trust, env, account)
        rows.append({"check": "trust", "role": env, "ok": not problems,
                     "detail": "; ".join(problems) or f"only {subject(env)}"})
        rows.append({"check": "inline only", "role": env, "ok": not attached and bool(inline),
                     "detail": f"inline: {', '.join(sorted(inline)) or 'none'}; "
                               f"attached: {', '.join(attached) or 'none'}"})
        for label, doc, is_trust in [("trust policy", trust, True),
                                     *[(f"policy {n}", d, False) for n, d in sorted(inline.items())]]:
            findings = validate(aws, doc, is_trust)
            bad = blocking(findings)
            rows.append({"check": "access analyzer", "role": env, "ok": not bad,
                         "detail": f"{label}: " + (", ".join(f"{f['findingType']} {f['issueCode']}" for f in findings)
                                                   or "no findings")})
        policies = list(inline.values())
        for case in (c for c in CASES if c.role == env):
            decision = simulate(aws, policies, case, arns)
            rows.append({"check": case.expect, "role": env, "ok": passes(case.expect, decision),
                         "detail": f"{case.action} on {case.resource}: {case.why} -> {decision}"})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", default="portfolio-read", help="AWS CLI profile (default: portfolio-read)")
    p.add_argument("--out", type=Path, help="also write the results here as JSON")
    args = p.parse_args(argv)
    try:
        rows = run_checks(cli(args.profile))
    except (RuntimeError, KeyError, IndexError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"could not run the IAM checks: {e}", file=sys.stderr)
        return 2
    for row in rows:
        print(f"{'ok  ' if row['ok'] else 'FAIL'}  {row['role']:<10}  {row['check']:<15}  {row['detail']}")
    failed = sum(not r["ok"] for r in rows)
    print(f"{len(rows)} checks, {failed} failed")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"checks": rows, "failed": failed}, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
