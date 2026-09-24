terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.65"
    }
  }

  # The first apply can't use this bucket, because the apply creates it. So the first run
  # uses local state (a git-ignored override.tf), then moves it here with
  #   terraform init -backend-config=backend.hcl -migrate-state
  # docs/aws.md has the steps.
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project     = "portfolio"
      Environment = "shared"
      ManagedBy   = "terraform/bootstrap"
      Repository  = var.github_repository
    }
  }
}
