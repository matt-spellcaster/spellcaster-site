# Several of these name the account, so they belong in your terminal and in GitHub secrets,
# never in a committed file.

output "state_bucket" {
  description = "Goes in backend.hcl, and in the TF_STATE_BUCKET repository secret."
  value       = aws_s3_bucket.state.bucket
}

output "qa_role_arn" {
  description = "The AWS_ROLE_ARN secret on the qa environment."
  value       = aws_iam_role.ci["qa"].arn
}

output "production_role_arn" {
  description = "The AWS_ROLE_ARN secret on the production environment."
  value       = aws_iam_role.ci["production"].arn
}

output "cloudflare_qa_name_servers" {
  description = "Add each as an NS record named qa at Cloudflare (DNS only)."
  value       = aws_route53_zone.qa.name_servers
}

output "cloudflare_validation_records" {
  description = "Add each as a CNAME at Cloudflare (DNS only), and keep them: renewals use them."
  value = [
    for o in aws_acm_certificate.production.domain_validation_options : {
      type    = o.resource_record_type
      name    = trimsuffix(trimsuffix(o.resource_record_name, "."), ".${var.domain}")
      content = trimsuffix(o.resource_record_value, ".")
    }
  ]
}

output "production_certificate_status" {
  description = "PENDING_VALIDATION until the Cloudflare CNAMEs resolve, then ISSUED."
  value       = aws_acm_certificate.production.status
}

# For infra/envs (M4b); none of these is secret.
output "shared" {
  description = "IDs infra/envs uses."
  value = {
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
    response_headers_policy  = { for k, p in aws_cloudfront_response_headers_policy.site : k => p.id }
    qa_zone_id               = aws_route53_zone.qa.zone_id
    alerts_topic             = aws_sns_topic.alerts.name
  }
}
