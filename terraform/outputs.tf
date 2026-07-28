output "data_bucket_name" {
  description = "S3 bucket used to store events.csv and products.csv."
  value       = aws_s3_bucket.data.id
}

output "models_bucket_name" {
  description = "S3 bucket used to store trained model artifacts."
  value       = aws_s3_bucket.models.id
}

output "model_train_ecr_repository_url" {
  description = "ECR repository URL for the model_train image."
  value       = aws_ecr_repository.services["model_train"].repository_url
}

output "model_train_image_uri" {
  description = "Full Docker image URI used by the ECS training task."
  value       = local.model_train_image_uri
}

output "model_train_ecs_cluster_name" {
  description = "ECS cluster responsible for running model_train."
  value       = aws_ecs_cluster.model_train.name
}

output "model_train_ecs_task_definition_arn" {
  description = "ECS task definition used to run model_train."
  value       = aws_ecs_task_definition.model_train.arn
}

output "model_package_group_name" {
  description = "SageMaker Model Registry group where new models are registered."
  value       = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
}

output "model_train_log_group" {
  description = "CloudWatch log group used by the model_train container."
  value       = aws_cloudwatch_log_group.model_train.name
}

output "model_train_ecs_task_role_arn" {
  description = "IAM role assumed by the ECS training task."
  value       = aws_iam_role.ecs_task.arn
}

output "model_train_ecs_security_group_id" {
  description = "Security group used by the ECS training task."
  value       = aws_security_group.model_train.id
}

output "model_train_ecs_subnet_ids" {
  description = "Default VPC subnet IDs used by the ECS training task."
  value       = data.aws_subnets.default.ids
}
