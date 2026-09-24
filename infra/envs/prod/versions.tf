terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.65"
    }
  }

  # The bucket's name contains the account ID, so it isn't here: the Deploy production job
  # passes the TF_STATE_BUCKET secret as -backend-config="bucket=...".
  backend "s3" {
    key          = "envs/prod/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = [var.account_id]

  # Exactly the four tag keys the CI role accepts (infra/bootstrap/main.tf), on everything.
  # The Environment tag is what lets portfolio-prod manage its own CloudFront resources.
  default_tags {
    tags = {
      Project     = "portfolio"
      Environment = "production"
      ManagedBy   = "terraform/envs/prod"
      Repository  = var.github_repository
    }
  }
}
