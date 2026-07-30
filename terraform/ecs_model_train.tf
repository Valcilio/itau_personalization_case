data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_subnet" "default" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
}

resource "aws_security_group" "model_train" {
  name        = "${var.project_name}-model-train-ecs"
  description = "Security group for the model_train ECS task."
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
    Service = "model-train"
  }
}

resource "aws_ecs_cluster" "model_train" {
  name = "${var.project_name}-model-train"

  tags = {
    Project = var.project_name
    Service = "model-train"
  }
}

resource "aws_ecs_task_definition" "model_train" {
  family                   = "${var.project_name}-model-train"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "model-train"
      image     = local.model_train_image_uri
      essential = true
      environment = [
        for key, value in local.model_train_environment : {
          name  = key
          value = value
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.model_train.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "model-train"
        }
      }
    }
  ])

  tags = {
    Project = var.project_name
    Service = "model-train"
  }
}

resource "null_resource" "run_model_train_on_apply" {
  count = var.run_model_train_on_apply ? 1 : 0

  triggers = {
    task_definition_arn = aws_ecs_task_definition.model_train.arn
    image_tag           = var.image_tag
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      aws ecs run-task \
        --region ${var.aws_region} \
        --cluster ${aws_ecs_cluster.model_train.name} \
        --task-definition ${aws_ecs_task_definition.model_train.arn} \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.model_train.id}],assignPublicIp=ENABLED}"
    EOT
    interpreter = ["/bin/bash", "-c"]
  }

  depends_on = [
    aws_ecs_task_definition.model_train,
    aws_ecs_cluster.model_train,
    aws_security_group.model_train,
  ]
}
