resource "aws_sns_topic" "model_drift_alerts" {
  name = "${var.project_name}-model-drift-alerts"

  tags = {
    Project = var.project_name
    Service = "model-drift-monitor"
  }
}

resource "aws_sns_topic_subscription" "model_drift_email" {
  topic_arn = aws_sns_topic.model_drift_alerts.arn
  protocol  = "email"
  endpoint  = var.drift_alert_email
}
