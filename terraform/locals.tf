data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  ecr_repositories = {
    model_train                = "personalization-model-train"
    model_predict              = "personalization-model-predict"
    predictions_retriever_api  = "personalization-predictions-retriever-api"
  }

  model_train_image_uri   = "${aws_ecr_repository.services["model_train"].repository_url}:${var.image_tag}"
  model_predict_image_uri = "${aws_ecr_repository.services["model_predict"].repository_url}:${var.image_tag}"

  model_train_environment = {
    MODEL_BUCKET             = aws_s3_bucket.models.id
    MODEL_PREFIX             = "models/purchase_propensity/${var.image_tag}"
    MODEL_PACKAGE_GROUP_NAME = aws_sagemaker_model_package_group.purchase_propensity.model_package_group_name
    INFERENCE_IMAGE_URI      = local.model_predict_image_uri
    CLOUDWATCH_LOG_GROUP     = aws_cloudwatch_log_group.model_train.name
    AWS_REGION               = var.aws_region
    MODEL_VERSION            = var.image_tag
    LOCAL_EVENTS_PATH        = "/opt/ml/input/data/training/events.csv"
    LOCAL_PRODUCTS_PATH      = "/opt/ml/input/data/training/products.csv"
    LOG_LEVEL                = "INFO"
  }

  sagemaker_pipeline_definition = jsonencode({
    Version = "2020-12-01"
    Parameters = [
      {
        Name         = "ImageTag"
        Type         = "String"
        DefaultValue = var.image_tag
      }
    ]
    Steps = [
      {
        Name = "TrainPurchasePropensityModel"
        Type = "Training"
        Arguments = {
          AlgorithmSpecification = {
            TrainingImage     = local.model_train_image_uri
            TrainingInputMode   = "File"
          }
          Environment = local.model_train_environment
          InputDataConfig = [
            {
              ChannelName = "training"
              ContentType = "text/csv"
              DataSource = {
                S3DataSource = {
                  S3DataType               = "S3Prefix"
                  S3Uri                    = "s3://${aws_s3_bucket.data.id}/${var.training_data_prefix}/"
                  S3DataDistributionType   = "FullyReplicated"
                }
              }
            }
          ]
          OutputDataConfig = {
            S3OutputPath = "s3://${aws_s3_bucket.models.id}/sagemaker/train/output/"
          }
          ResourceConfig = {
            InstanceCount  = 1
            InstanceType   = var.training_instance_type
            VolumeSizeInGB = 30
          }
          RoleArn = aws_iam_role.sagemaker_execution.arn
          StoppingCondition = {
            MaxRuntimeInSeconds = 3600
          }
        }
      }
    ]
  })
}
