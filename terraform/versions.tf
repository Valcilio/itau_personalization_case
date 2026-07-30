terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    bucket         = "personalization-terraform-state-272175292064"
    key            = "terraform/state/model-train/terraform.tfstate"
    region         = "us-east-1"
    use_lockfile = true
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
