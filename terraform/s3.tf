resource "aws_s3_bucket" "data" {
  bucket        = "${var.project_name}-data-${local.account_id}"
  force_destroy = true

  tags = {
    Project = var.project_name
    Purpose = "training-data"
  }
}

resource "aws_s3_bucket" "models" {
  bucket        = "${var.project_name}-models-${local.account_id}"
  force_destroy = true

  tags = {
    Project = var.project_name
    Purpose = "model-artifacts"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket = aws_s3_bucket.models.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "training_events" {
  bucket = aws_s3_bucket.data.id
  key    = "${var.training_data_prefix}/events.csv"
  source = "${path.module}/../data/events.csv"
  etag   = filemd5("${path.module}/../data/events.csv")
}

resource "aws_s3_object" "training_products" {
  bucket = aws_s3_bucket.data.id
  key    = "${var.training_data_prefix}/products.csv"
  source = "${path.module}/../data/products.csv"
  etag   = filemd5("${path.module}/../data/products.csv")
}
