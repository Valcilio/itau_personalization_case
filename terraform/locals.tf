data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  ecr_repositories = {
    model_train = "personalization-model-train"
  }

  model_train_image_uri = "${aws_ecr_repository.services["model_train"].repository_url}:${var.image_tag}"
  ecs_subnet_ids        = join(",", data.aws_subnets.default.ids)

  model_train_environment = {
    DATA_BUCKET              = aws_s3_bucket.data.id
    DATA_PREFIX              = var.training_data_prefix
    MODEL_BUCKET             = aws_s3_bucket.models.id
    MODEL_PREFIX             = "models/purchase_propensity/${var.image_tag}"
    MODEL_OUTPUT_DIR         = "/tmp/model"
    TRAINING_DATA_DIR        = "/tmp/training"
    MODEL_PACKAGE_GROUP_NAME = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
    INFERENCE_IMAGE_URI      = local.model_train_image_uri
    AWS_REGION               = var.aws_region
    MODEL_VERSION            = var.image_tag
    LOG_LEVEL                = "INFO"
  }
}
