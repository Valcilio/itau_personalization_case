resource "aws_dynamodb_table" "predictions" {
  name         = "${var.project_name}-predictions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "product_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "product_id"
    type = "S"
  }

  tags = {
    Project = var.project_name
    Purpose = "prediction-outputs"
  }
}
