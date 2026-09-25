# Read by the Deploy production job (publish and smoke test), which masks the account ID.

output "domain" {
  description = "The site's one name. The smoke test asks for it, and for www."
  value       = var.domain
}

output "bucket" {
  description = "Where the site's files go. Its name contains the account ID."
  value       = module.site.bucket
}

output "distribution_id" {
  description = "For the invalidation after each publish."
  value       = module.site.distribution_id
}

output "distribution_domain_name" {
  description = "The dxxxx.cloudfront.net name: the smoke test's target now, and Cloudflare's CNAME target at launch (M5)."
  value       = module.site.distribution_domain_name
}
