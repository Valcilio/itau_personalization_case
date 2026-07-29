output "data_bucket_name" {
  description = "S3 bucket used to store events.csv, products.csv and prediction outputs."
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

output "model_predict_ecr_repository_url" {
  description = "ECR repository URL for the model_predict image."
  value       = aws_ecr_repository.services["model_predict"].repository_url
}

output "model_train_image_uri" {
  description = "Full Docker image URI used by the ECS training task."
  value       = local.model_train_image_uri
}

output "model_predict_image_uri" {
  description = "Full Docker image URI used by the ECS prediction task."
  value       = local.model_predict_image_uri
}

output "model_train_ecs_cluster_name" {
  description = "ECS cluster responsible for running model_train."
  value       = aws_ecs_cluster.model_train.name
}

output "model_predict_ecs_cluster_name" {
  description = "ECS cluster responsible for running model_predict."
  value       = aws_ecs_cluster.model_predict.name
}

output "model_train_ecs_task_definition_arn" {
  description = "ECS task definition used to run model_train."
  value       = aws_ecs_task_definition.model_train.arn
}

output "model_predict_ecs_task_definition_arn" {
  description = "ECS task definition used to run model_predict."
  value       = aws_ecs_task_definition.model_predict.arn
}

output "model_package_group_name" {
  description = "SageMaker Model Registry group where new models are registered."
  value       = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
}

output "model_train_log_group" {
  description = "CloudWatch log group used by the model_train container."
  value       = aws_cloudwatch_log_group.model_train.name
}

output "model_predict_log_group" {
  description = "CloudWatch log group used by the model_predict container."
  value       = aws_cloudwatch_log_group.model_predict.name
}

output "model_train_ecs_task_role_arn" {
  description = "IAM role assumed by the ECS training and prediction tasks."
  value       = aws_iam_role.ecs_task.arn
}

output "model_train_ecs_security_group_id" {
  description = "Security group used by the ECS training task."
  value       = aws_security_group.model_train.id
}

output "model_predict_ecs_security_group_id" {
  description = "Security group used by the ECS prediction task."
  value       = aws_security_group.model_predict.id
}

output "model_train_ecs_subnet_ids" {
  description = "Default VPC subnet IDs used by the ECS tasks."
  value       = data.aws_subnets.default.ids
}

output "predictions_prefix" {
  description = "S3 prefix where model_predict writes prediction outputs."
  value       = var.predictions_prefix
}

output "predictions_dynamodb_table_name" {
  description = "DynamoDB table replaced on every model_predict run with the latest scores."
  value       = aws_dynamodb_table.predictions.name
}

output "predictions_dynamodb_table_arn" {
  description = "ARN of the DynamoDB predictions table."
  value       = aws_dynamodb_table.predictions.arn
}

output "recommendations_api_ecr_repository_url" {
  description = "ECR repository URL for the recommendations API image."
  value       = aws_ecr_repository.services["recommendations_api"].repository_url
}

output "recommendations_api_image_uri" {
  description = "Full Docker image URI used by the recommendations API service."
  value       = local.recommendations_api_image_uri
}

output "recommendations_api_ecs_cluster_name" {
  description = "ECS cluster running the online recommendations API."
  value       = aws_ecs_cluster.recommendations_api.name
}

output "recommendations_api_ecs_service_name" {
  description = "ECS service name for the recommendations API."
  value       = aws_ecs_service.recommendations_api.name
}

output "recommendations_api_alb_dns_name" {
  description = "Internal ALB DNS name fronting the recommendations API."
  value       = aws_lb.recommendations.dns_name
}

output "recommendations_api_gateway_endpoint" {
  description = "Public API Gateway HTTP endpoint for the recommendations API."
  value       = aws_apigatewayv2_api.recommendations.api_endpoint
}

output "recommendations_api_vpc_link_subnet_ids" {
  description = "Subnet IDs used by the API Gateway VPC Link (unsupported AZs excluded)."
  value       = local.vpc_link_subnet_ids
}

output "recommendations_api_log_group" {
  description = "CloudWatch log group used by the recommendations API container."
  value       = aws_cloudwatch_log_group.recommendations_api.name
}

output "recommendations_api_key_ssm_parameter" {
  description = "SSM parameter containing the public API key (header x-api-key)."
  value       = aws_ssm_parameter.recommendations_api_key.name
}

output "recommendations_api_key" {
  description = "API key required to call the public recommendations API."
  value       = random_password.recommendations_api_key.result
  sensitive   = true
}

output "model_train_ecs_run_task_command" {
  description = "Command to run a one-off model_train batch task."
  value = format(
    "aws ecs run-task --region %s --cluster %s --task-definition %s --launch-type FARGATE --network-configuration \"awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=ENABLED}\"",
    var.aws_region,
    aws_ecs_cluster.model_train.name,
    aws_ecs_task_definition.model_train.family,
    join(",", data.aws_subnets.default.ids),
    aws_security_group.model_train.id,
  )
}

output "model_predict_ecs_run_task_command" {
  description = "Command to run a one-off model_predict batch task."
  value = format(
    "aws ecs run-task --region %s --cluster %s --task-definition %s --launch-type FARGATE --network-configuration \"awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=ENABLED}\"",
    var.aws_region,
    aws_ecs_cluster.model_predict.name,
    aws_ecs_task_definition.model_predict.family,
    join(",", data.aws_subnets.default.ids),
    aws_security_group.model_predict.id,
  )
}
