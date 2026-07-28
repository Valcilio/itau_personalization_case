"""Entrypoint for the SageMaker model training pipeline."""

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from model_train.domain.gateways.awsconnector import AwsConnector
from model_train.domain.gateways.modelhandler import ModelHandler
from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


@dataclass(frozen=True)
class PipelineResult:
    """Summary returned after a full training pipeline execution."""

    model_version: str
    model_output_dir: str
    model_s3_uri: str
    model_package_arn: str
    accuracy: str
    roc_auc: str
    validated_customers: int


logger = ModelTrainerLogger("main")


def load_config() -> dict[str, str]:
    """Load runtime configuration from environment variables.

    Returns:
        Dictionary with local paths, AWS settings and model versioning data.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return {
        "data_bucket": os.getenv("DATA_BUCKET", ""),
        "data_prefix": os.getenv("DATA_PREFIX", "training-data"),
        "model_bucket": os.getenv("MODEL_BUCKET", ""),
        "model_prefix": os.getenv("MODEL_PREFIX", f"models/purchase_propensity/{timestamp}"),
        "model_output_dir": os.getenv("SM_MODEL_DIR", "/opt/ml/model"),
        "training_data_dir": os.getenv("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"),
        "model_package_group_name": os.getenv(
            "MODEL_PACKAGE_GROUP_NAME",
            "purchase-propensity-model-group",
        ),
        "inference_image_uri": os.getenv("INFERENCE_IMAGE_URI", ""),
        "model_version": os.getenv("MODEL_VERSION", f"1.0.{timestamp}"),
        "local_events_path": os.getenv("LOCAL_EVENTS_PATH", "data/events.csv"),
        "local_products_path": os.getenv("LOCAL_PRODUCTS_PATH", "data/products.csv"),
    }


def load_datasets(
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load training datasets from S3 or from the local filesystem.

    Args:
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway used when ``DATA_BUCKET`` is configured.

    Returns:
        Events and products dataframes ready for feature engineering.
    """
    if config["data_bucket"]:
        logger.info(
            "dataset_source_selected",
            source="s3",
            bucket=config["data_bucket"],
            prefix=config["data_prefix"],
        )
        dataset_paths = aws_connector.download_training_dataset(
            bucket=config["data_bucket"],
            prefix=config["data_prefix"],
            local_dir=config["training_data_dir"],
        )
        events_path = dataset_paths["events"]
        products_path = dataset_paths["products"]
    else:
        logger.info(
            "dataset_source_selected",
            source="local",
            events_path=config["local_events_path"],
            products_path=config["local_products_path"],
        )
        events_path = Path(config["local_events_path"])
        products_path = Path(config["local_products_path"])

    events = pd.read_csv(events_path)
    products = pd.read_csv(products_path)
    logger.info(
        "datasets_loaded",
        events_rows=len(events),
        products_rows=len(products),
        events_path=str(events_path),
        products_path=str(products_path),
    )
    return events, products


def publish_model_artifact(
    output_dir: Path,
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> str:
    """Publish local model artifacts to S3 when configured.

    Args:
        output_dir: Directory containing ``model.pkl`` and ``model_card.json``.
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway responsible for uploading files.

    Returns:
        Local or remote URI pointing to the primary model artifact.
    """
    if not config["model_bucket"]:
        logger.warning(
            "model_publish_skipped",
            reason="model_bucket_not_configured",
            local_artifact=str(output_dir / "model.pkl"),
        )
        return str(output_dir / "model.pkl")

    return aws_connector.upload_model_directory(
        local_dir=output_dir,
        bucket=config["model_bucket"],
        prefix=config["model_prefix"],
    )


def register_model_version(
    model_s3_uri: str,
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> str:
    """Register the trained model in SageMaker Model Registry when configured.

    Args:
        model_s3_uri: S3 URI of the uploaded model artifact.
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway responsible for registry operations.

    Returns:
        Model package ARN when registration succeeds, otherwise an empty string.
    """
    if not config["model_bucket"] or not config["inference_image_uri"]:
        logger.warning(
            "model_registry_registration_skipped",
            reason="model_bucket_or_inference_image_not_configured",
        )
        return ""

    return aws_connector.register_model_package(
        model_package_group_name=config["model_package_group_name"],
        model_data_url=model_s3_uri,
        image_uri=config["inference_image_uri"],
        model_name="purchase_propensity_v1",
        description=(
            f"Purchase propensity model version {config['model_version']} "
            "generated by SageMaker training pipeline."
        ),
    )


def run_training_pipeline() -> PipelineResult:
    """Execute the full training pipeline end to end.

    Returns:
        Summary with metrics, local paths and AWS registration details.
    """
    config = load_config()
    logger.info(
        "training_pipeline_started",
        model_version=config["model_version"],
        model_output_dir=config["model_output_dir"],
    )

    aws_connector = AwsConnector()
    model_handler = ModelHandler()

    events, products = load_datasets(config, aws_connector)
    output_dir = Path(config["model_output_dir"])
    handler_result = model_handler.train_and_persist(
        events,
        products,
        output_dir,
        config["model_version"],
    )

    model_s3_uri = publish_model_artifact(output_dir, config, aws_connector)
    model_package_arn = register_model_version(model_s3_uri, config, aws_connector)

    training_result = handler_result.training_result
    result = PipelineResult(
        model_version=config["model_version"],
        model_output_dir=str(output_dir),
        model_s3_uri=model_s3_uri,
        model_package_arn=model_package_arn,
        accuracy=str(training_result.metrics["accuracy"]),
        roc_auc=str(training_result.metrics["roc_auc"]),
        validated_customers=training_result.validated_customers,
    )
    logger.info(
        "training_pipeline_completed",
        model_version=result.model_version,
        model_s3_uri=result.model_s3_uri,
        model_package_arn=result.model_package_arn,
        accuracy=result.accuracy,
        roc_auc=result.roc_auc,
        validated_customers=result.validated_customers,
    )
    return result


def main() -> int:
    """Configure logging and run the SageMaker training pipeline."""
    ModelTrainerLogger.configure()

    try:
        result = run_training_pipeline()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("training_pipeline_failed")
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
