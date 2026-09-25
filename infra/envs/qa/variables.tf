variable "account_id" {
  description = "The portfolio-site account (the AWS_ACCOUNT_ID secret). The provider refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be the 12-digit account ID."
  }
}

variable "origin_access_control_id" {
  description = "bootstrap's shared.origin_access_control_id output (the ORIGIN_ACCESS_CONTROL_ID repository variable). There's no lookup by name."
  type        = string
}

variable "basic_auth_sha256" {
  description = "The SHA-256 (hex) of the Authorization header QA asks for. scripts/ci/qa_auth.sh makes it from the password in SSM. No default: QA never goes up without a password."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.basic_auth_sha256))
    error_message = "basic_auth_sha256 must be 64 lower-case hex characters."
  }
}

variable "domain" {
  description = "The site's domain. QA answers at qa.<domain>, whose zone is in Route 53 (bootstrap)."
  type        = string
  default     = "spellcaster.foo"
}

variable "github_repository" {
  description = "The repository that deploys, as owner/name. Used for the Repository tag."
  type        = string
  default     = "matt-spellcaster/spellcaster-site-WIP"
}
