# Read by the QA up workflow (publish and smoke test), which masks the account ID.

output "domain" {
  description = "QA's one name. The smoke test asks for it."
  value       = local.qa_domain
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
  description = "The dxxxx.cloudfront.net name, which qa.<domain> points at."
  value       = module.site.distribution_domain_name
}
