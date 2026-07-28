data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  bucket_name  = "${var.project_name}-terraform-state-${local.account_id}"
  lock_table   = "${var.project_name}-terraform-locks"
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = local.bucket_name

  tags = {
    Project = var.project_name
    Purpose = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "terraform_state_prefix" {
  bucket  = aws_s3_bucket.terraform_state.id
  key     = "${var.state_key_prefix}/.keep"
  content = ""
}

resource "aws_dynamodb_table" "terraform_locks" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project = var.project_name
    Purpose = "terraform-state-lock"
  }
}
