resource "aws_security_group" "recommendations_alb" {
  name        = "${var.project_name}-recommendations-alb"
  description = "ALB security group for recommendations API."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.recommendations_vpc_link.id]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_security_group" "recommendations_api" {
  name        = "${var.project_name}-recommendations-api-ecs"
  description = "Security group for recommendations API ECS tasks."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.recommendations_alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_security_group" "recommendations_vpc_link" {
  name        = "${var.project_name}-recommendations-vpclink"
  description = "Security group for API Gateway VPC Link ENIs."
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_lb" "recommendations" {
  name               = "${var.project_name}-recs-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.recommendations_alb.id]
  subnets            = data.aws_subnets.default.ids

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_lb_target_group" "recommendations" {
  name        = "${var.project_name}-recs-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_lb_listener" "recommendations" {
  load_balancer_arn = aws_lb.recommendations.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.recommendations.arn
  }
}

resource "aws_ecs_cluster" "recommendations_api" {
  name = "${var.project_name}-recommendations-api"

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_ecs_task_definition" "recommendations_api" {
  family                   = "${var.project_name}-recommendations-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.recommendations_api_cpu
  memory                   = var.recommendations_api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "recommendations-api"
      image     = local.recommendations_api_image_uri
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in local.recommendations_api_environment : {
          name  = key
          value = value
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.recommendations_api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "recommendations-api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_ecs_service" "recommendations_api" {
  name            = "${var.project_name}-recommendations-api"
  cluster         = aws_ecs_cluster.recommendations_api.id
  task_definition = aws_ecs_task_definition.recommendations_api.arn
  desired_count   = var.recommendations_api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.recommendations_api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.recommendations.arn
    container_name   = "recommendations-api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.recommendations]

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_appautoscaling_target" "recommendations_api" {
  max_capacity       = var.recommendations_api_max_capacity
  min_capacity       = var.recommendations_api_min_capacity
  resource_id        = "service/${aws_ecs_cluster.recommendations_api.name}/${aws_ecs_service.recommendations_api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "recommendations_api_cpu" {
  name               = "${var.project_name}-recommendations-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.recommendations_api.resource_id
  scalable_dimension = aws_appautoscaling_target.recommendations_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.recommendations_api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "recommendations_api_memory" {
  name               = "${var.project_name}-recommendations-api-memory"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.recommendations_api.resource_id
  scalable_dimension = aws_appautoscaling_target.recommendations_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.recommendations_api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

resource "aws_apigatewayv2_vpc_link" "recommendations" {
  name               = "${var.project_name}-recommendations-vpclink"
  security_group_ids = [aws_security_group.recommendations_vpc_link.id]
  subnet_ids         = local.vpc_link_subnet_ids

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_apigatewayv2_api" "recommendations" {
  name          = "${var.project_name}-recommendations-api"
  protocol_type = "HTTP"

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}

resource "aws_apigatewayv2_integration" "recommendations" {
  api_id                 = aws_apigatewayv2_api.recommendations.id
  integration_type       = "HTTP_PROXY"
  integration_uri        = aws_lb_listener.recommendations.arn
  integration_method     = "ANY"
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.recommendations.id
  payload_format_version = "1.0"
}

resource "aws_apigatewayv2_route" "recommendations_health" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_route" "recommendations_metrics" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "GET /metrics"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_route" "recommendations_get" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "GET /recommendation/{user_id}"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_route" "recommendations_get_plural" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "GET /recommendations/{user_id}"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_route" "recommendations_filtered" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "POST /recommendation_filtered"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_route" "recommendations_filtered_plural" {
  api_id    = aws_apigatewayv2_api.recommendations.id
  route_key = "POST /recommendations_filtered"
  target    = "integrations/${aws_apigatewayv2_integration.recommendations.id}"
}

resource "aws_apigatewayv2_stage" "recommendations" {
  api_id      = aws_apigatewayv2_api.recommendations.id
  name        = "$default"
  auto_deploy = true

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
  description = "Usage plan for the public recommendations API (API key required on protected routes)."

  api_stages {
    api_id = aws_apigatewayv2_api.recommendations.id
    stage  = aws_apigatewayv2_stage.recommendations.name

    throttle {
      path        = "/metrics/GET"
      burst_limit = 100
      rate_limit  = 50
    }

    throttle {
      path        = "/recommendation/{user_id}/GET"
      burst_limit = 100
      rate_limit  = 50
    }

    throttle {
      path        = "/recommendations/{user_id}/GET"
      burst_limit = 100
      rate_limit  = 50
    }

    throttle {
      path        = "/recommendation_filtered/POST"
      burst_limit = 100
      rate_limit  = 50
    }

    throttle {
      path        = "/recommendations_filtered/POST"
      burst_limit = 100
      rate_limit  = 50
    }
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
  description = "API Gateway API key for the public recommendations API (header x-api-key)."
  type        = "SecureString"
  value       = aws_api_gateway_api_key.recommendations.value

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}
