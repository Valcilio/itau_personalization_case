terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    bucket         = "personalization-terraform-state-272175292064"
    key            = "terraform/state/model-train/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "personalization-terraform-locks"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
