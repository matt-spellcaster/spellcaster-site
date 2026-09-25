output "bucket" {
  description = "Where the site's files go. Its name contains the account ID."
  value       = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  description = "For invalidations and the traffic alarms."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_domain_name" {
  description = "The distribution's own dxxxx.cloudfront.net name, which DNS points at."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "distribution_hosted_zone_id" {
  description = "CloudFront's own Route 53 zone, for alias records (QA's)."
  value       = aws_cloudfront_distribution.site.hosted_zone_id
}
