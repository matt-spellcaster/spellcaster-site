variable "account_id" {
  description = "The portfolio-site AWS account. The provider refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be the 12-digit account ID."
  }
}

variable "domain" {
  description = "The site's domain. Its DNS stays at Cloudflare; only qa.<domain> is delegated here."
  type        = string
  default     = "spellcaster.foo"
}

variable "github_repository" {
  description = "The repository that deploys, as owner/name. Used for the Repository tag."
  type        = string
  default     = "matt-spellcaster/spellcaster-site-WIP"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

# The CI roles trust these IDs, which never change. Names can: a renamed repository keeps its
# ID, and a new repository with an old name gets a new one.
variable "github_owner_id" {
  description = "Numeric ID of the repository owner (gh api users/<owner> --jq .id)."
  type        = number
  default     = 329836411
}

variable "github_repo_id" {
  description = "Numeric ID of the repository (gh api repos/<owner>/<name> --jq .id)."
  type        = number
  default     = 1384189986
}

variable "alert_email" {
  description = "Where budget and traffic alerts go. AWS emails it once to confirm the subscription."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "budget_limit_usd" {
  description = "Monthly cost budget for this account, in US dollars."
  type        = number
  default     = 5
}
