# QA, built by the QA up workflow and torn down by QA down (every night too), as portfolio-qa.
# It's production's twin at qa.<domain>, behind a password and noindex. Its bucket isn't
# versioned and empties itself on destroy: nothing on QA is kept.

locals {
  qa_domain = "qa.${var.domain}"
}

# Bootstrap issues the certificate and owns the zone. most_recent picks the new certificate
# when bootstrap replaces it (docs/aws.md, "Known limits"), and ISSUED makes a plan fail rather
# than use a pending one.
data "aws_acm_certificate" "site" {
  domain      = local.qa_domain
  statuses    = ["ISSUED"]
  types       = ["AMAZON_ISSUED"]
  most_recent = true
}

data "aws_cloudfront_response_headers_policy" "site" {
  name = "portfolio-qa-headers" # production's headers, plus X-Robots-Tag: noindex, nofollow
}

data "aws_route53_zone" "qa" {
  name         = local.qa_domain
  private_zone = false
}

module "site" {
  source = "../../modules/site"

  environment                = "qa"
  account_id                 = var.account_id
  domain                     = local.qa_domain
  aliases                    = [local.qa_domain]
  certificate_arn            = data.aws_acm_certificate.site.arn
  origin_access_control_id   = var.origin_access_control_id
  response_headers_policy_id = data.aws_cloudfront_response_headers_policy.site.id
  versioned                  = false
  force_destroy              = true
  basic_auth_sha256          = var.basic_auth_sha256
}

# qa.<domain> itself, at the zone's apex: the only records the QA role may write.
resource "aws_route53_record" "site" {
  for_each = toset(["A", "AAAA"])

  zone_id = data.aws_route53_zone.qa.zone_id
  name    = local.qa_domain
  type    = each.key

  alias {
    name                   = module.site.distribution_domain_name
    zone_id                = module.site.distribution_hosted_zone_id
    evaluate_target_health = false
  }
}
