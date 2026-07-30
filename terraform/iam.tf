data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project_name}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json

  tags = {
    Project = var.project_name
    Service = "ecs"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_task" {
  statement {
    sid = "S3Access"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
      aws_s3_bucket.models.arn,
      "${aws_s3_bucket.models.arn}/*",
    ]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      aws_cloudwatch_log_group.model_train.arn,
      "${aws_cloudwatch_log_group.model_train.arn}:*",
      aws_cloudwatch_log_group.model_predict.arn,
      "${aws_cloudwatch_log_group.model_predict.arn}:*",
      aws_cloudwatch_log_group.recommendations_api.arn,
      "${aws_cloudwatch_log_group.recommendations_api.arn}:*",
      aws_cloudwatch_log_group.model_drift_monitor.arn,
      "${aws_cloudwatch_log_group.model_drift_monitor.arn}:*",
    ]
  }

  statement {
    sid = "EcsRunTask"
    actions = [
      "ecs:RunTask",
    ]
    resources = [
      aws_ecs_task_definition.model_train.arn_without_revision,
      aws_ecs_task_definition.model_predict.arn_without_revision,
      aws_ecs_task_definition.model_drift_monitor.arn_without_revision,
      aws_ecs_cluster.model_train.arn,
      aws_ecs_cluster.model_predict.arn,
      aws_ecs_cluster.model_drift_monitor.arn,
    ]
  }

  statement {
    sid = "EcsRunTaskPassRole"
    actions = [
      "iam:PassRole",
    ]
    resources = [
      aws_iam_role.ecs_task_execution.arn,
      aws_iam_role.ecs_task.arn,
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid = "EcsDescribeTasks"
    actions = [
      "ecs:DescribeTasks",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeClusters",
    ]
    resources = ["*"]
  }

  statement {
    sid = "SnsDriftAlerts"
    actions = [
      "sns:Publish",
    ]
    resources = [
      aws_sns_topic.model_drift_alerts.arn,
    ]
  }

  statement {
    sid = "ModelRegistry"
    actions = [
      "sagemaker:CreateModelPackage",
      "sagemaker:DescribeModelPackage",
      "sagemaker:DescribeModelPackageGroup",
      "sagemaker:CreateModelPackageGroup",
      "sagemaker:ListModelPackages",
      "sagemaker:UpdateModelPackage",
    ]
    resources = ["*"]
  }

  statement {
    sid = "EcrReadForModelRegistryValidation"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
    ]
    resources = ["*"]
  }

  statement {
    sid = "DynamoDBPredictions"
    actions = [
      "dynamodb:Scan",
      "dynamodb:Query",
      "dynamodb:GetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      aws_dynamodb_table.predictions.arn,
      "${aws_dynamodb_table.predictions.arn}/index/*",
      aws_dynamodb_table.integration_predictions.arn,
      "${aws_dynamodb_table.integration_predictions.arn}/index/*",
    ]
  }
}

resource "aws_iam_role" "ecs_task" {
  name               = "${var.project_name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json

  tags = {
    Project = var.project_name
    Service = "ecs"
  }
}

resource "aws_iam_role_policy" "ecs_task" {
  name   = "${var.project_name}-ecs-task"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task.json
}
