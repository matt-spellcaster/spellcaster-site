# GitHub Actions reaches AWS through OIDC; there are no long-lived AWS keys anywhere.
#
#   portfolio-qa    jobs in the "qa" GitHub environment: builds and destroys the QA site
#   portfolio-prod  jobs in the "production" environment (main only): deploys production
#
# Both run Terraform on their own state key and their own site, and nothing else. What they
# may touch is fenced by name (buckets, state keys, alarms) or by the Environment tag
# (CloudFront), and the guardrails policy denies what they must never do, whatever the allow
# list says. Neither may change a certificate: bootstrap issues both. scripts/ci/
# iam_policy_tests.py checks all of it.

locals {
  oidc_host = "token.actions.githubusercontent.com"
  owner     = split("/", var.github_repository)[0]
  # GitHub's immutable subject is repo:<owner>@<owner id>/<name>@<repo id>:<context>. The IDs
  # never change, so the name is a wildcard: renaming the repository (say, dropping "-WIP")
  # doesn't lock CI out, and a new repository that takes an old name has a different ID.
  # The pattern ends in "@<repo id>:environment:<env>", and GitHub encodes a ":" in an
  # environment name, so only this repository's own environments match.
  subject_prefix = "repo:${local.owner}@${var.github_owner_id}/*@${var.github_repo_id}"

  cloudfront_distributions = "arn:aws:cloudfront::${local.account_id}:distribution/*"
  cloudfront_functions     = "arn:aws:cloudfront::${local.account_id}:function/*"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "ci_trust" {
  for_each = local.environments

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "${local.oidc_host}:sub"
      values   = ["${local.subject_prefix}:environment:${each.key}"]
    }
  }
}

resource "aws_iam_role" "ci" {
  for_each = local.environments

  name                 = each.value.role
  description          = "GitHub Actions, ${each.key} environment of ${var.github_repository}"
  assume_role_policy   = data.aws_iam_policy_document.ci_trust[each.key].json
  max_session_duration = 3600

  tags = {
    Environment = each.key
  }
}

# --- What each role may do ------------------------------------------------------------

data "aws_iam_policy_document" "ci_access" {
  for_each = local.environments
  # checkov:skip=CKV_AWS_356:The Read statement is read-only and account-wide (list calls can't be scoped, and plans must refresh), and CreateDistribution and CreateFunction take no resource ARN, so they're conditioned on their tags. Every write is scoped by name or by the Environment tag.

  # What only this environment may do (below).
  source_policy_documents = [
    each.key == "qa" ? data.aws_iam_policy_document.qa_access.json : data.aws_iam_policy_document.production_access.json
  ]

  # Terraform state: its own key only. Listing the bucket lets Terraform tell "no state yet"
  # apart from "access denied"; it shows key names, never contents.
  statement {
    sid       = "StateList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]
  }
  statement {
    sid       = "StateFile"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.state.arn}/${each.value.state_key}"]
  }
  statement {
    sid       = "StateLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/${each.value.state_key}.tflock"]
  }

  # Reading configuration, so plans can refresh and CI can check what exists.
  statement {
    sid = "Read"
    actions = [
      "acm:DescribeCertificate",
      "acm:GetCertificate",
      "acm:ListCertificates",
      "acm:ListTagsForCertificate",
      "cloudfront:Describe*",
      "cloudfront:Get*",
      "cloudfront:List*",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "route53:GetChange",
      "route53:GetHostedZone",
      "route53:ListHostedZones",
      "route53:ListHostedZonesByName",
      "route53:ListResourceRecordSets",
      "route53:ListTagsForResource",
      "sns:GetTopicAttributes",
      "sns:ListTagsForResource",
      "sns:ListTopics",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  # The environment's own site bucket, found by name.
  statement {
    sid = "SiteBucket"
    actions = concat([
      "s3:CreateBucket",
      "s3:GetAccelerateConfiguration",
      "s3:GetBucket*",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:ListTagsForResource",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
      "s3:TagResource",
      "s3:UntagResource",
    ], each.key == "qa" ? ["s3:DeleteBucket"] : [])
    resources = ["arn:aws:s3:::${each.value.bucket}"]
  }
  statement {
    sid = "SiteObjects"
    actions = concat(
      ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"],
      each.key == "qa" ? ["s3:DeleteObjectVersion"] : [],
    )
    resources = ["arn:aws:s3:::${each.value.bucket}/*"]
  }

  # CloudFront distributions and functions have random IDs, so they're fenced by tag: new
  # ones must carry this environment's tag (and only the four standard tag keys), and
  # existing ones must already have it.
  statement {
    sid       = "CloudFrontCreateTagged"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.tag_keys
    }
  }
  # Creating with tags also tags the new resource, before it has an Environment tag.
  statement {
    sid       = "CloudFrontTagNew"
    actions   = ["cloudfront:TagResource"]
    resources = [local.cloudfront_distributions, local.cloudfront_functions]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.tag_keys
    }
  }
  statement {
    sid = "CloudFrontManageOwn"
    actions = concat([
      "cloudfront:CreateInvalidation",
      "cloudfront:DeleteFunction",
      "cloudfront:PublishFunction",
      "cloudfront:TagResource",
      "cloudfront:TestFunction",
      "cloudfront:UntagResource",
      "cloudfront:UpdateDistribution",
      "cloudfront:UpdateFunction",
    ], each.key == "qa" ? ["cloudfront:DeleteDistribution"] : [])
    resources = [local.cloudfront_distributions, local.cloudfront_functions]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "StringEqualsIfExists"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = local.tag_keys
    }
  }
}

# QA only: its site records and its Basic-auth password.
data "aws_iam_policy_document" "qa_access" {
  statement {
    sid       = "QaSiteRecords"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = [aws_route53_zone.qa.arn]
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsRecordTypes"
      values   = ["A", "AAAA"]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
      values   = [local.qa_domain]
    }
  }
  statement {
    # Created by hand, so the value never enters Terraform state. alias/aws/ssm needs no
    # KMS grant: its key policy lets anyone in the account decrypt through SSM.
    sid       = "QaPassword"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}:${local.account_id}:parameter/portfolio/qa/basic-auth-password"]
  }
}

# Production only: its traffic alarms.
data "aws_iam_policy_document" "production_access" {
  statement {
    sid = "ProductionAlarms"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = ["arn:aws:cloudwatch:${local.region}:${local.account_id}:alarm:portfolio-production-*"]
  }
}

# --- What each role must never do, whatever the allows say --------------------------

data "aws_iam_policy_document" "ci_guardrails" {
  for_each = local.environments

  source_policy_documents = each.key == "production" ? [data.aws_iam_policy_document.production_guardrails.json] : []

  statement {
    sid       = "NoIdentityOrgOrBilling"
    effect    = "Deny"
    actions   = ["iam:*", "organizations:*", "budgets:*", "account:*", "s3:PutAccountPublicAccessBlock"]
    resources = ["*"]
  }

  # Moving a domain from one distribution to another is how a QA stack could take over
  # production's name.
  statement {
    sid       = "NoAliasMoves"
    effect    = "Deny"
    actions   = ["cloudfront:AssociateAlias", "cloudfront:UpdateDomainAssociation"]
    resources = ["*"]
  }

  # The shared origin access control and header policies live in bootstrap.
  statement {
    sid    = "NoSharedCloudFrontPolicies"
    effect = "Deny"
    actions = [
      "cloudfront:CreateCachePolicy",
      "cloudfront:CreateOriginAccessControl",
      "cloudfront:CreateOriginRequestPolicy",
      "cloudfront:CreateResponseHeadersPolicy",
      "cloudfront:DeleteCachePolicy",
      "cloudfront:DeleteOriginAccessControl",
      "cloudfront:DeleteOriginRequestPolicy",
      "cloudfront:DeleteResponseHeadersPolicy",
      "cloudfront:UpdateCachePolicy",
      "cloudfront:UpdateOriginAccessControl",
      "cloudfront:UpdateOriginRequestPolicy",
      "cloudfront:UpdateResponseHeadersPolicy",
    ]
    resources = ["*"]
  }

  # Tags are the fence, so a role may not move a resource across it, in either direction:
  # no tagging anything that carries another environment's tag, and no giving anything
  # another environment's tag. (A new resource has no tags yet, hence the Null tests.)
  statement {
    sid       = "NoRetaggingOtherEnvironments"
    effect    = "Deny"
    actions   = ["cloudfront:TagResource", "cloudfront:UntagResource"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "Null"
      variable = "aws:ResourceTag/Environment"
      values   = ["false"]
    }
  }
  statement {
    sid       = "NoTaggingIntoOtherEnvironments"
    effect    = "Deny"
    actions   = ["cloudfront:CreateDistribution", "cloudfront:CreateFunction", "cloudfront:TagResource"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "Null"
      variable = "aws:RequestTag/Environment"
      values   = ["false"]
    }
  }
  statement {
    sid       = "NoRemovingTheEnvironmentTag"
    effect    = "Deny"
    actions   = ["cloudfront:UntagResource"]
    resources = ["*"]
    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Environment"]
    }
  }

  # Bootstrap issues both certificates, so CI never changes one, and no private key can
  # leave AWS (the org's DenyExportableCerts SCP says the same, in case the account leaves).
  statement {
    sid    = "NoCertificateChanges"
    effect = "Deny"
    actions = [
      "acm:AddTagsToCertificate",
      "acm:DeleteCertificate",
      "acm:ExportCertificate",
      "acm:ImportCertificate",
      "acm:RemoveTagsFromCertificate",
      "acm:RenewCertificate",
      "acm:RequestCertificate",
      "acm:ResendValidationEmail",
      "acm:RevokeCertificate",
      "acm:UpdateCertificateOptions",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "NoHostedZoneChanges"
    effect    = "Deny"
    actions   = ["route53:CreateHostedZone", "route53:DeleteHostedZone"]
    resources = ["*"]
  }
}

# Production can't delete the site or its history (a lifecycle rule could expire every old
# version, so it can't set one), and has no business with DNS: its DNS is at Cloudflare.
data "aws_iam_policy_document" "production_guardrails" {
  statement {
    sid    = "NoProductionDeletes"
    effect = "Deny"
    actions = [
      "cloudfront:DeleteDistribution",
      "s3:DeleteBucket",
      "s3:DeleteObjectVersion",
      "s3:PutLifecycleConfiguration",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "NoProductionDnsChanges"
    effect = "Deny"
    actions = [
      "route53:Associate*",
      "route53:Change*",
      "route53:Create*",
      "route53:Delete*",
      "route53:Disassociate*",
      "route53:Update*",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci_access" {
  for_each = local.environments

  name   = "access"
  role   = aws_iam_role.ci[each.key].id
  policy = data.aws_iam_policy_document.ci_access[each.key].json
}

resource "aws_iam_role_policy" "ci_guardrails" {
  for_each = local.environments

  name   = "guardrails"
  role   = aws_iam_role.ci[each.key].id
  policy = data.aws_iam_policy_document.ci_guardrails[each.key].json
}
