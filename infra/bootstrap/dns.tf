# qa.<domain> is delegated from Cloudflare to this zone (4 NS records at Cloudflare), so the
# QA pipeline can manage its own records without a Cloudflare token. The zone outlives every
# QA stack: its name servers are what Cloudflare points at.
#
# The records below are fixed, and the QA role can't change them: it may only write A/AAAA
# at the zone apex and ACM's validation CNAMEs (see ci_roles.tf).

resource "aws_route53_zone" "qa" {
  name    = local.qa_domain
  comment = "QA site. Delegated from Cloudflare; the QA role writes only A/AAAA and ACM CNAMEs."

  lifecycle {
    prevent_destroy = true
  }
}

# Nothing sends mail as qa.<domain>, so say so: receivers reject anything that claims to.
resource "aws_route53_record" "qa_dmarc" {
  zone_id = aws_route53_zone.qa.zone_id
  name    = "_dmarc.${local.qa_domain}"
  type    = "TXT"
  ttl     = 3600
  records = ["v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s"]
}

resource "aws_route53_record" "qa_spf" {
  zone_id = aws_route53_zone.qa.zone_id
  name    = local.qa_domain
  type    = "TXT"
  ttl     = 3600
  records = ["v=spf1 -all"]
}

# A null MX (RFC 7505): no mail is accepted for qa.<domain> either.
resource "aws_route53_record" "qa_null_mx" {
  zone_id = aws_route53_zone.qa.zone_id
  name    = local.qa_domain
  type    = "MX"
  ttl     = 3600
  records = ["0 ."]
}

# Only Amazon may issue certificates for the QA name, the same as the apex at Cloudflare.
resource "aws_route53_record" "qa_caa" {
  zone_id = aws_route53_zone.qa.zone_id
  name    = local.qa_domain
  type    = "CAA"
  ttl     = 3600
  records = ["0 issue \"amazon.com\""]
}
