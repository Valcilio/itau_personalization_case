data "aws_iam_policy_document" "sagemaker_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sagemaker_execution" {
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
    sid = "ECRAccess"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [for repository in aws_ecr_repository.services : repository.arn]
  }

  statement {
    sid       = "ECRAuthorization"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
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
}

resource "aws_iam_role" "sagemaker_execution" {
  name               = "${var.project_name}-sagemaker-execution"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy" "sagemaker_execution" {
  name   = "${var.project_name}-sagemaker-execution"
  role   = aws_iam_role.sagemaker_execution.id
  policy = data.aws_iam_policy_document.sagemaker_execution.json
}

data "aws_iam_policy_document" "sagemaker_pipeline_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sagemaker_pipeline" {
  statement {
    sid = "PipelineExecution"
    actions = [
      "sagemaker:CreateTrainingJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:StopTrainingJob",
      "sagemaker:AddTags",
      "sagemaker:ListTags",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "PassRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.sagemaker_execution.arn]
  }
}

resource "aws_iam_role" "sagemaker_pipeline" {
  name               = "${var.project_name}-sagemaker-pipeline"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_pipeline_assume_role.json

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy" "sagemaker_pipeline" {
  name   = "${var.project_name}-sagemaker-pipeline"
  role   = aws_iam_role.sagemaker_pipeline.id
  policy = data.aws_iam_policy_document.sagemaker_pipeline.json
}
