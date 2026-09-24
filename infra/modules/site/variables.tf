variable "environment" {
  description = "qa or production. Names the bucket and the function, and must match the CI role's Environment tag."
  type        = string

  validation {
    condition     = contains(["qa", "production"], var.environment)
    error_message = "environment must be qa or production."
  }
}

variable "account_id" {
  description = "The portfolio-site account. The bucket's name ends in -<account>-us-east-1-an."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be the 12-digit account ID."
  }
}

variable "domain" {
  description = "The site's one name. Every other host (www, the *.cloudfront.net name) redirects to it."
  type        = string
}

variable "aliases" {
  description = "The names the distribution answers to. The certificate must cover each one."
  type        = list(string)
}

variable "certificate_arn" {
  description = "An ISSUED certificate from bootstrap, in us-east-1."
  type        = string
}

variable "origin_access_control_id" {
  description = "bootstrap's origin access control (the shared output). CloudFront signs every request to the bucket with it."
  type        = string

  validation {
    condition     = can(regex("^[A-Z0-9]{8,20}$", var.origin_access_control_id))
    error_message = "origin_access_control_id must be an origin access control ID, like E2ABC3DEF4GHIJ."
  }
}

variable "response_headers_policy_id" {
  description = "bootstrap's security-header policy for this environment."
  type        = string
}

variable "versioned" {
  description = "Keep every old version of every file. On for production, so a bad publish can be undone."
  type        = bool
}

variable "force_destroy" {
  description = "Let terraform destroy empty the bucket first. Only QA, which is torn down every night."
  type        = bool
}
