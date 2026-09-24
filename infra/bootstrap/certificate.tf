# The production certificate (apex and www). Its DNS lives at Cloudflare, so the two
# validation CNAMEs are added there by hand (the cloudflare_validation_records output) and
# stay for as long as the site exists: ACM renews through them.
#
# There's no waiter here on purpose. Validation needs those manual records, so an apply would
# otherwise hang; infra/envs/prod waits for ISSUED instead, before CloudFront uses it.

resource "aws_acm_certificate" "production" {
  domain_name               = var.domain
  subject_alternative_names = ["www.${var.domain}"]
  validation_method         = "DNS"

  options {
    certificate_transparency_logging_preference = "ENABLED"
    export                                      = "DISABLED"
  }

  tags = {
    Environment = "production"
  }

  lifecycle {
    create_before_destroy = true
  }
}
