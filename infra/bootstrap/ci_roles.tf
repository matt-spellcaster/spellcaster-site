# GitHub Actions reaches AWS through OIDC; there are no long-lived AWS keys anywhere.
#
#   portfolio-qa    jobs in the "qa" GitHub environment: builds and destroys the QA site
#   portfolio-prod  jobs in the "production" environment (main only): deploys production
#
# Both run Terraform on their own state key and their own site, and nothing else. What they
# may touch is fenced by name (buckets, state keys, alarms) or by the Environment tag
# (CloudFront, certificates), and the guardrails policy denies what they must never do,
# whatever the allow list says. scripts/ci/iam_policy_tests.py checks both.

locals {
  oidc_host = "token.actions.githubusercontent.com"
  owner     = split("/", var.github_repository)[0]
  # GitHub's immutable subject is repo:<owner>@<owner id>/<name>@<repo id>:<context>. The IDs
  # never change, so the name is a wildcard: renaming the repository (say, dropping "-WIP")
  # doesn't lock CI out, and a new repository that takes an old name has a different ID.
  # Names can't contain "@" or "/", so the wildcard can't reach past its own segment.
  subject_prefix = "repo:${local.owner}@${var.github_owner_id}/*@${var.github_repo_id}"

  cloudfront_distributions = "arn:aws:cloudfront::${local.account_id}:distribution/*"
  cloudfront_functions     = "arn:aws:cloudfront::${local.account_id}:function/*"
  certificates             = "arn:aws:acm:${var.region}:${local.account_id}:certificate/*"
  # ACM's validation records are _<32 hex characters>.<name>; each ? is one character.
  acm_validation_name = "_${join("", [for _ in range(32) : "?"])}.${local.qa_domain}"
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

  # QA only: its own certificate, DNS records and Basic-auth password.
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
      sid       = "QaCertificateRequest"
      actions   = ["acm:RequestCertificate"]
      resources = ["*"]
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "acm:DomainNames"
        values   = [local.qa_domain]
      }
      condition {
        test     = "StringEquals"
        variable = "acm:ValidationMethod"
        values   = ["DNS"]
      }
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/Environment"
        values   = ["qa"]
      }
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "aws:TagKeys"
        values   = local.tag_keys
      }
    }
  }
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
      # Tagging happens as part of the request, before the certificate has any tags.
      sid       = "QaCertificateTag"
      actions   = ["acm:AddTagsToCertificate"]
      resources = [local.certificates]
      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/Environment"
        values   = ["qa"]
      }
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "aws:TagKeys"
        values   = local.tag_keys
      }
    }
  }
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
      sid       = "QaCertificateManage"
      actions   = ["acm:DeleteCertificate", "acm:RemoveTagsFromCertificate"]
      resources = [local.certificates]
      condition {
        test     = "StringEquals"
        variable = "aws:ResourceTag/Environment"
        values   = ["qa"]
      }
    }
  }
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
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
  }
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
      sid       = "QaValidationRecords"
      actions   = ["route53:ChangeResourceRecordSets"]
      resources = [aws_route53_zone.qa.arn]
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "route53:ChangeResourceRecordSetsRecordTypes"
        values   = ["CNAME"]
      }
      condition {
        test     = "ForAllValues:StringLike"
        variable = "route53:ChangeResourceRecordSetsNormalizedRecordNames"
        values   = [local.acm_validation_name]
      }
    }
  }
  dynamic "statement" {
    for_each = each.key == "qa" ? [1] : []
    content {
      # Created by hand, so the value never enters Terraform state. alias/aws/ssm needs no
      # KMS grant: its key policy lets anyone in the account decrypt through SSM.
      sid       = "QaPassword"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/portfolio/qa/basic-auth-password"]
    }
  }

  # Production only: its traffic alarms.
  dynamic "statement" {
    for_each = each.key == "production" ? [1] : []
    content {
      sid = "ProductionAlarms"
      actions = [
        "cloudwatch:DeleteAlarms",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
      ]
      resources = ["arn:aws:cloudwatch:${var.region}:${local.account_id}:alarm:portfolio-production-*"]
    }
  }
}

# --- What each role must never do, whatever the allows say --------------------------

data "aws_iam_policy_document" "ci_guardrails" {
  for_each = local.environments

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

  # Tags are the fence, so a role may not move a resource across it: no tagging anything
  # that carries another environment's tag. (A new resource has no tags yet, hence the Null
  # test; the allow list already requires this environment's tag on it.)
  statement {
    sid    = "NoRetaggingOtherEnvironments"
    effect = "Deny"
    actions = [
      "acm:AddTagsToCertificate",
      "acm:RemoveTagsFromCertificate",
      "cloudfront:TagResource",
      "cloudfront:UntagResource",
    ]
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
    sid       = "NoRemovingTheEnvironmentTag"
    effect    = "Deny"
    actions   = ["acm:RemoveTagsFromCertificate", "cloudfront:UntagResource"]
    resources = ["*"]
    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "aws:TagKeys"
      values   = ["Environment"]
    }
  }

  # A certificate whose private key can leave AWS. The org's DenyExportableCerts SCP says
  # the same; this keeps it true if the account ever leaves the org.
  statement {
    sid       = "NoCertificateExport"
    effect    = "Deny"
    actions   = ["acm:ExportCertificate"]
    resources = ["*"]
  }
  statement {
    sid       = "NoExportableCertificates"
    effect    = "Deny"
    actions   = ["acm:RequestCertificate"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "acm:Export"
      values   = ["ENABLED"]
    }
  }

  statement {
    sid       = "NoHostedZoneChanges"
    effect    = "Deny"
    actions   = ["route53:CreateHostedZone", "route53:DeleteHostedZone"]
    resources = ["*"]
  }

  # Production can't delete the site or its history, and has no business with certificates
  # or DNS: bootstrap owns its certificate, and its DNS is at Cloudflare.
  dynamic "statement" {
    for_each = each.key == "production" ? [1] : []
    content {
      sid       = "NoProductionDeletes"
      effect    = "Deny"
      actions   = ["cloudfront:DeleteDistribution", "s3:DeleteBucket", "s3:DeleteObjectVersion"]
      resources = ["*"]
    }
  }
  dynamic "statement" {
    for_each = each.key == "production" ? [1] : []
    content {
      sid    = "NoProductionCertificateOrDnsChanges"
      effect = "Deny"
      actions = [
        "acm:AddTagsToCertificate",
        "acm:DeleteCertificate",
        "acm:ImportCertificate",
        "acm:RemoveTagsFromCertificate",
        "acm:RenewCertificate",
        "acm:RequestCertificate",
        "acm:ResendValidationEmail",
        "acm:RevokeCertificate",
        "acm:UpdateCertificateOptions",
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
