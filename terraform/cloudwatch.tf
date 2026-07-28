resource "aws_cloudwatch_log_group" "model_train" {
  name              = "/ecs/${var.project_name}/model-train"
  retention_in_days = 30

  tags = {
    Project = var.project_name
    Service = "model-train"
  }
}
