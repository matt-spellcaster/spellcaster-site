# Both certificates live here, so CI never requests, changes or deletes one.
#
# The production certificate (apex and www). Its DNS lives at Cloudflare, so the two
# validation CNAMEs are added there by hand (the cloudflare_validation_records output) and
# stay for as long as the site exists: ACM renews through them.
#
# There's no waiter here on purpose. Validation needs those manual records, so an apply would
# otherwise hang. infra/envs/prod looks up only an ISSUED certificate instead, so its plan
# fails rather than hand CloudFront a pending one.

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

# The QA certificate. Its validation record goes in the qa zone, so it validates by itself once
# Cloudflare delegates qa (the NS records in docs/dns.md) and renews the same way. Issuing it
# once here, rather than per QA build, keeps certificate requests out of CI altogether.
resource "aws_acm_certificate" "qa" {
  domain_name       = local.qa_domain
  validation_method = "DNS"

  options {
    certificate_transparency_logging_preference = "ENABLED"
    export                                      = "DISABLED"
  }

  tags = {
    Environment = "qa"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "qa_certificate_validation" {
  for_each = {
    for o in aws_acm_certificate.qa.domain_validation_options : o.domain_name => o
  }

  zone_id = aws_route53_zone.qa.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  ttl     = 300
  records = [each.value.resource_record_value]
}
