terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
  # Remote state. Bucket and lock table come from infra/bootstrap/github-oidc.yaml; the deploy
  # workflow passes bucket, key, region and table with -backend-config.
  backend "s3" {}
}

provider "aws" {
  # The public blockchain dataset lives in us-east-2; keeping compute in the same region
  # avoids cross-region transfer charges.
  region = var.region
  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
