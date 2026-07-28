output "state_bucket_name" {
  description = "S3 bucket used to store Terraform remote state."
  value       = aws_s3_bucket.terraform_state.id
}

output "state_key_prefix" {
  description = "S3 prefix reserved for Terraform state files."
  value       = var.state_key_prefix
}

output "state_key" {
  description = "Default state file path for the main Terraform stack."
  value       = "${var.state_key_prefix}/model-train/terraform.tfstate"
}

output "dynamodb_table_name" {
  description = "DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.terraform_locks.name
}

output "backend_config" {
  description = "Values to use with terraform init -backend-config."
  value = {
    bucket         = aws_s3_bucket.terraform_state.id
    key            = "${var.state_key_prefix}/model-train/terraform.tfstate"
    region         = var.aws_region
    dynamodb_table = aws_dynamodb_table.terraform_locks.name
    encrypt        = true
  }
}
