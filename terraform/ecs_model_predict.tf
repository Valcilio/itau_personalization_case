resource "aws_security_group" "model_predict" {
  name        = "${var.project_name}-model-predict-ecs"
  description = "Security group for the model_predict ECS task."
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Service = "model-predict"
  }
}

resource "aws_ecs_cluster" "model_predict" {
  name = "${var.project_name}-model-predict"

  tags = {
    Project = var.project_name
    Service = "model-predict"
  }
}

resource "aws_ecs_task_definition" "model_predict" {
  family                   = "${var.project_name}-model-predict"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "model-predict"
      image     = local.model_predict_image_uri
      essential = true
      environment = [
        for key, value in local.model_predict_environment : {
          name  = key
          value = value
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.model_predict.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "model-predict"
        }
      }
    }
  ])

  tags = {
    Project = var.project_name
    Service = "model-predict"
  }
}

resource "null_resource" "run_model_predict_on_apply" {
  count = var.run_model_predict_on_apply ? 1 : 0

  triggers = {
    task_definition_arn = aws_ecs_task_definition.model_predict.arn
    image_tag           = var.image_tag
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      aws ecs run-task \
        --region ${var.aws_region} \
        --cluster ${aws_ecs_cluster.model_predict.name} \
        --task-definition ${aws_ecs_task_definition.model_predict.arn} \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.model_predict.id}],assignPublicIp=ENABLED}"
    EOT
    interpreter = ["/bin/bash", "-c"]
  }

  depends_on = [
    aws_ecs_task_definition.model_predict,
    aws_ecs_cluster.model_predict,
    aws_security_group.model_predict,
  ]
}
