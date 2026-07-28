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
  description = "Full Docker image URI used by the SageMaker training step."
  value       = local.model_train_image_uri
}

output "model_train_pipeline_name" {
  description = "SageMaker pipeline responsible for running model_train."
  value       = aws_sagemaker_pipeline.model_train.pipeline_name
}

output "model_train_pipeline_execution_display_name" {
  description = "Display name used when triggering the SageMaker pipeline, if enabled."
  value       = var.trigger_training_pipeline ? "train-${var.image_tag}" : null
}

output "model_package_group_name" {
  description = "SageMaker Model Registry group where new models are registered."
  value       = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
}

output "model_train_log_group" {
  description = "CloudWatch log group used by the model_train container."
  value       = aws_cloudwatch_log_group.model_train.name
}

output "sagemaker_execution_role_arn" {
  description = "IAM role assumed by the SageMaker training job."
  value       = aws_iam_role.sagemaker_execution.arn
}
