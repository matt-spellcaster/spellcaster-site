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
