locals {
  recommendations_backend_base_url = "http://${aws_lb.recommendations_nlb.dns_name}"
}

resource "aws_api_gateway_vpc_link" "recommendations" {
  name        = "${var.project_name}-recommendations-vpclink"
  description = "VPC link from REST API Gateway to the recommendations NLB."
  target_arns = [aws_lb.recommendations_nlb.arn]

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_api_gateway_rest_api" "recommendations" {
  name        = "${var.project_name}-recommendations-api"
  description = "REST API for purchase-propensity recommendations."

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_api_gateway_resource" "recommendations_health" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "health"
}

resource "aws_api_gateway_method" "recommendations_health" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendations_health.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "recommendations_health" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendations_health.id
  http_method             = aws_api_gateway_method.recommendations_health.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "GET"
  uri                     = "${local.recommendations_backend_base_url}/health"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id
}

resource "aws_api_gateway_resource" "recommendations_metrics" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "metrics"
}

resource "aws_api_gateway_method" "recommendations_metrics" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendations_metrics.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "recommendations_metrics" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendations_metrics.id
  http_method             = aws_api_gateway_method.recommendations_metrics.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "GET"
  uri                     = "${local.recommendations_backend_base_url}/metrics"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id
}

resource "aws_api_gateway_resource" "recommendation" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "recommendation"
}

resource "aws_api_gateway_resource" "recommendation_user" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_resource.recommendation.id
  path_part   = "{user_id}"
}

resource "aws_api_gateway_method" "recommendation_get" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendation_user.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true

  request_parameters = {
    "method.request.path.user_id" = true
  }
}

resource "aws_api_gateway_integration" "recommendation_get" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendation_user.id
  http_method             = aws_api_gateway_method.recommendation_get.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "GET"
  uri                     = "${local.recommendations_backend_base_url}/recommendation/{user_id}"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id

  request_parameters = {
    "integration.request.path.user_id" = "method.request.path.user_id"
  }
}

resource "aws_api_gateway_resource" "recommendations" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "recommendations"
}

resource "aws_api_gateway_resource" "recommendations_user" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_resource.recommendations.id
  path_part   = "{user_id}"
}

resource "aws_api_gateway_method" "recommendations_get" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendations_user.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true

  request_parameters = {
    "method.request.path.user_id" = true
  }
}

resource "aws_api_gateway_integration" "recommendations_get" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendations_user.id
  http_method             = aws_api_gateway_method.recommendations_get.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "GET"
  uri                     = "${local.recommendations_backend_base_url}/recommendations/{user_id}"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id

  request_parameters = {
    "integration.request.path.user_id" = "method.request.path.user_id"
  }
}

resource "aws_api_gateway_resource" "recommendation_filtered" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "recommendation_filtered"
}

resource "aws_api_gateway_method" "recommendation_filtered" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendation_filtered.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "recommendation_filtered" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendation_filtered.id
  http_method             = aws_api_gateway_method.recommendation_filtered.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "POST"
  uri                     = "${local.recommendations_backend_base_url}/recommendation_filtered"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id
}

resource "aws_api_gateway_resource" "recommendations_filtered" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id
  parent_id   = aws_api_gateway_rest_api.recommendations.root_resource_id
  path_part   = "recommendations_filtered"
}

resource "aws_api_gateway_method" "recommendations_filtered" {
  rest_api_id      = aws_api_gateway_rest_api.recommendations.id
  resource_id      = aws_api_gateway_resource.recommendations_filtered.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "recommendations_filtered" {
  rest_api_id             = aws_api_gateway_rest_api.recommendations.id
  resource_id             = aws_api_gateway_resource.recommendations_filtered.id
  http_method             = aws_api_gateway_method.recommendations_filtered.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "POST"
  uri                     = "${local.recommendations_backend_base_url}/recommendations_filtered"
  connection_type         = "VPC_LINK"
  connection_id           = aws_api_gateway_vpc_link.recommendations.id
}

resource "aws_api_gateway_deployment" "recommendations" {
  rest_api_id = aws_api_gateway_rest_api.recommendations.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.recommendations_health.id,
      aws_api_gateway_method.recommendations_health.id,
      aws_api_gateway_integration.recommendations_health.id,
      aws_api_gateway_resource.recommendations_metrics.id,
      aws_api_gateway_method.recommendations_metrics.id,
      aws_api_gateway_integration.recommendations_metrics.id,
      aws_api_gateway_resource.recommendation.id,
      aws_api_gateway_resource.recommendation_user.id,
      aws_api_gateway_method.recommendation_get.id,
      aws_api_gateway_integration.recommendation_get.id,
      aws_api_gateway_resource.recommendations.id,
      aws_api_gateway_resource.recommendations_user.id,
      aws_api_gateway_method.recommendations_get.id,
      aws_api_gateway_integration.recommendations_get.id,
      aws_api_gateway_resource.recommendation_filtered.id,
      aws_api_gateway_method.recommendation_filtered.id,
      aws_api_gateway_integration.recommendation_filtered.id,
      aws_api_gateway_resource.recommendations_filtered.id,
      aws_api_gateway_method.recommendations_filtered.id,
      aws_api_gateway_integration.recommendations_filtered.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.recommendations_health,
    aws_api_gateway_integration.recommendations_metrics,
    aws_api_gateway_integration.recommendation_get,
    aws_api_gateway_integration.recommendations_get,
    aws_api_gateway_integration.recommendation_filtered,
    aws_api_gateway_integration.recommendations_filtered,
  ]
}

resource "aws_api_gateway_stage" "recommendations" {
  rest_api_id   = aws_api_gateway_rest_api.recommendations.id
  deployment_id = aws_api_gateway_deployment.recommendations.id
  stage_name    = "v1"

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_api_gateway_api_key" "recommendations" {
  name = "${var.project_name}-recommendations-api-key"

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_api_gateway_usage_plan" "recommendations" {
  name        = "${var.project_name}-recommendations-usage-plan"
  description = "Usage plan for the public recommendations REST API."

  api_stages {
    api_id = aws_api_gateway_rest_api.recommendations.id
    stage  = aws_api_gateway_stage.recommendations.stage_name
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_api_gateway_usage_plan_key" "recommendations" {
  key_id        = aws_api_gateway_api_key.recommendations.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.recommendations.id
}

resource "aws_ssm_parameter" "recommendations_api_key" {
  name        = "/${var.project_name}/recommendations-api/api-key"
  description = "API Gateway API key for the public recommendations REST API (header x-api-key)."
  type        = "SecureString"
  value       = aws_api_gateway_api_key.recommendations.value
  overwrite   = true

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}
