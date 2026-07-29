resource "aws_cloudwatch_log_group" "model_train" {
  name              = "/ecs/${var.project_name}/model-train"
  retention_in_days = 30

  tags = {
    Project = var.project_name
    Service = "model-train"
  }
}

resource "aws_cloudwatch_log_group" "model_predict" {
  name              = "/ecs/${var.project_name}/model-predict"
  retention_in_days = 30

  tags = {
    Project = var.project_name
    Service = "model-predict"
  }
}

resource "aws_cloudwatch_log_group" "recommendations_api" {
  name              = "/ecs/${var.project_name}/recommendations-api"
  retention_in_days = 30

  tags = {
    Project = var.project_name
    Service = "recommendations-api"
  }
}
