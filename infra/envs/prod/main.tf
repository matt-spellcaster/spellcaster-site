# Production, applied by the Deploy production job as portfolio-prod. The site answers at
# spellcaster.foo and www (which redirects), once Cloudflare points them here at launch (M5).
# Until then it's reachable only through its *.cloudfront.net name, which also redirects.

# Bootstrap issues the certificate. most_recent picks the new one when bootstrap replaces it
# (docs/aws.md, "Known limits"), and ISSUED makes a plan fail rather than use a pending one.
data "aws_acm_certificate" "site" {
  domain      = var.domain
  statuses    = ["ISSUED"]
  types       = ["AMAZON_ISSUED"]
  most_recent = true
}

data "aws_cloudfront_response_headers_policy" "site" {
  name = "portfolio-production-headers"
}

module "site" {
  source = "../../modules/site"

  environment                = "production"
  account_id                 = var.account_id
  domain                     = var.domain
  aliases                    = [var.domain, "www.${var.domain}"]
  certificate_arn            = data.aws_acm_certificate.site.arn
  origin_access_control_id   = var.origin_access_control_id
  response_headers_policy_id = data.aws_cloudfront_response_headers_policy.site.id
  versioned                  = true
  force_destroy              = false
}
