data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
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

resource "null_resource" "model_train_task_execution" {
  count = var.trigger_training_task ? 1 : 0

  triggers = {
    image_tag                = var.image_tag
    task_definition_revision = aws_ecs_task_definition.model_train.revision
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ecs run-task \
        --region ${var.aws_region} \
        --cluster ${aws_ecs_cluster.model_train.name} \
        --task-definition ${aws_ecs_task_definition.model_train.arn} \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${local.ecs_subnet_ids}],securityGroups=[${aws_security_group.model_train.id}],assignPublicIp=ENABLED}" \
        --started-by terraform-train-${var.image_tag}
    EOT
  }

  depends_on = [
    aws_s3_object.training_events,
    aws_s3_object.training_products,
    aws_ecs_task_definition.model_train,
  ]
}
