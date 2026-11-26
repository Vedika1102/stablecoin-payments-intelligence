terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
  # Remote state for a team setup (bucket + lock table created once, out of band):
  # backend "s3" {
  #   bucket         = "<org>-terraform-state"
  #   key            = "stablecoin-payments/terraform.tfstate"
  #   region         = "us-east-2"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
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
