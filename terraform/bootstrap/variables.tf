variable "aws_region" {
  description = "AWS region where the Terraform state backend will be created."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used to name the state backend resources."
  type        = string
  default     = "personalization"
}

variable "state_key_prefix" {
  description = "S3 prefix where Terraform state files are stored."
  type        = string
  default     = "terraform/state"
}
