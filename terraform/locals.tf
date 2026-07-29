data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  ecr_repositories = {
    model_train         = "personalization-model-train"
    model_predict       = "personalization-model-predict"
    recommendations_api = "personalization-recommendations-api"
  }

  model_train_image_uri         = "${aws_ecr_repository.services["model_train"].repository_url}:${var.image_tag}"
  model_predict_image_uri       = "${aws_ecr_repository.services["model_predict"].repository_url}:${var.image_tag}"
  recommendations_api_image_uri = "${aws_ecr_repository.services["recommendations_api"].repository_url}:${var.image_tag}"
  ecs_subnet_ids                = join(",", data.aws_subnets.default.ids)

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
    IMAGE_TAG                = var.image_tag
    LOG_LEVEL                = "INFO"
  }

  model_predict_environment = {
    DATA_BUCKET                = aws_s3_bucket.data.id
    DATA_PREFIX                = var.training_data_prefix
    PREDICTIONS_BUCKET         = aws_s3_bucket.data.id
    PREDICTIONS_PREFIX         = var.predictions_prefix
    PREDICTIONS_DYNAMODB_TABLE = aws_dynamodb_table.predictions.name
    MODEL_PACKAGE_GROUP_NAME   = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
    LOCAL_DATA_DIR             = "/tmp/prediction-data"
    LOCAL_MODEL_DIR            = "/tmp/prediction-model"
    LOCAL_OUTPUT_DIR           = "/tmp/prediction-output"
    AWS_REGION                 = var.aws_region
    LOG_LEVEL                  = "INFO"
  }

  recommendations_api_environment = {
    DATA_BUCKET                = aws_s3_bucket.data.id
    DATA_PREFIX                = var.training_data_prefix
    PREDICTIONS_DYNAMODB_TABLE = aws_dynamodb_table.predictions.name
    AWS_REGION                 = var.aws_region
    LOG_LEVEL                  = "INFO"
  }
}
