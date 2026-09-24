# One-time setup for the portfolio-site account, applied by hand with the portfolio-admin
# profile. It holds everything that is persistent, shared by QA and production, or too
# sensitive for CI to change: Terraform state, the GitHub OIDC trust and the two CI roles,
# the qa.<domain> zone, both certificates, the CloudFront policies, alerts and the budget. infra/envs/{prod,qa} (CI) build the sites on top of it.

locals {
  account_id = var.account_id
  # CloudFront only uses certificates from us-east-1, and the org's RegionLock SCP allows only
  # us-east-1, so this is fixed.
  region    = "us-east-1"
  qa_domain = "qa.${var.domain}"
  # Buckets in the account-regional namespace: the name ends in -<account>-<region>-an, and
  # only this account can ever create it, so nobody can squat a name we'll need later.
  bucket_suffix = "${local.account_id}-${local.region}-an"
  state_bucket  = "portfolio-tfstate-${local.bucket_suffix}"

  # The two CI environments, keyed by the GitHub environment and the Environment tag.
  environments = {
    qa = {
      role      = "portfolio-qa"
      bucket    = "portfolio-qa-${local.bucket_suffix}"
      state_key = "envs/qa/terraform.tfstate"
    }
    production = {
      role      = "portfolio-prod"
      bucket    = "portfolio-production-${local.bucket_suffix}"
      state_key = "envs/prod/terraform.tfstate"
    }
  }

  # The only tag keys CI may set: exactly the provider's default_tags.
  tag_keys = ["Project", "Environment", "ManagedBy", "Repository"]
}

# No bucket in this account may ever be public. The sites are private buckets that only
# CloudFront reads, so this costs nothing and stops a bucket policy mistake from leaking.
resource "aws_s3_account_public_access_block" "this" {
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
