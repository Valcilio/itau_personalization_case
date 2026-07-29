"""Entrypoint for the model prediction pipeline."""

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

from model_predict.domain.gateways.awsconnector import AwsConnector
from model_predict.domain.gateways.modelhandler import ModelHandler
from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


@dataclass(frozen=True)
class PipelineResult:
    """Summary returned after a full prediction pipeline execution."""

    model_package_group_name: str
    model_package_version: int
    predictions_s3_uri: str
    prediction_rows: int
    validated_costumers: int


logger = ModelRunnerLogger("main")


def load_config() -> dict[str, str]:
    """Load runtime configuration from environment variables.

    Returns:
        Dictionary with AWS settings and local working directories.

    Raises:
        ValueError: If required environment variables are missing.
    """
    data_bucket = os.getenv("DATA_BUCKET", "").strip()
    predictions_bucket = os.getenv("PREDICTIONS_BUCKET", "").strip() or os.getenv(
        "DATA_BUCKET",
        "",
    ).strip()
    if not data_bucket:
        raise ValueError("DATA_BUCKET is required to load prediction datasets from S3")
    if not predictions_bucket:
        raise ValueError("PREDICTIONS_BUCKET or DATA_BUCKET is required to upload outputs")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return {
        "data_bucket": data_bucket,
        "data_prefix": os.getenv("DATA_PREFIX", "training-data"),
        "predictions_bucket": predictions_bucket,
        "predictions_prefix": os.getenv("PREDICTIONS_PREFIX", "predictions"),
        "predictions_filename": os.getenv(
            "PREDICTIONS_FILENAME",
            f"predictions_{timestamp}.csv",
        ),
        "model_package_group_name": os.getenv(
            "MODEL_PACKAGE_GROUP_NAME",
            "purchase-propensity-model-group",
        ),
        "local_data_dir": os.getenv("LOCAL_DATA_DIR", "/tmp/prediction-data"),
        "local_model_dir": os.getenv("LOCAL_MODEL_DIR", "/tmp/prediction-model"),
        "local_output_dir": os.getenv("LOCAL_OUTPUT_DIR", "/tmp/prediction-output"),
    }


def load_datasets(
    config: dict[str, str],
    aws_connector: AwsConnector,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load prediction datasets from S3.

    Args:
        config: Pipeline configuration produced by ``load_config``.
        aws_connector: AWS gateway used to download feature source CSVs.

    Returns:
        Events and products dataframes ready for feature engineering.
    """
    logger.info(
        "dataset_source_selected",
        source="s3",
        bucket=config["data_bucket"],
        prefix=config["data_prefix"],
    )
    dataset_paths = aws_connector.download_prediction_dataset(
        bucket=config["data_bucket"],
        prefix=config["data_prefix"],
        local_dir=config["local_data_dir"],
    )
    events = pd.read_csv(dataset_paths["events"])
    products = pd.read_csv(dataset_paths["products"])
    logger.info(
        "datasets_loaded",
        events_rows=len(events),
        products_rows=len(products),
        events_path=str(dataset_paths["events"]),
        products_path=str(dataset_paths["products"]),
    )
    return events, products


def run_prediction_pipeline() -> PipelineResult:
    """Execute the full prediction pipeline end to end.

    Returns:
        Summary with output URI and prediction counts.
    """
    config = load_config()
    logger.info(
        "prediction_pipeline_started",
        model_package_group_name=config["model_package_group_name"],
        model_package_version=AwsConnector.HARDCODED_MODEL_PACKAGE_VERSION,
    )

    aws_connector = AwsConnector()
    model_handler = ModelHandler()

    events, products = load_datasets(config, aws_connector)
    artifact_dir = aws_connector.download_model_artifact(
        model_package_group_name=config["model_package_group_name"],
        local_dir=config["local_model_dir"],
    )
    handler_result = model_handler.run_predictions(
        events=events,
        products=products,
        artifact_dir=artifact_dir,
    )

    predictions_s3_uri = aws_connector.upload_predictions(
        predictions=handler_result.predictions,
        bucket=config["predictions_bucket"],
        prefix=config["predictions_prefix"],
        filename=config["predictions_filename"],
        local_dir=config["local_output_dir"],
    )

    result = PipelineResult(
        model_package_group_name=config["model_package_group_name"],
        model_package_version=AwsConnector.HARDCODED_MODEL_PACKAGE_VERSION,
        predictions_s3_uri=predictions_s3_uri,
        prediction_rows=len(handler_result.predictions),
        validated_costumers=handler_result.validated_costumers,
    )
    logger.info(
        "prediction_pipeline_completed",
        predictions_s3_uri=result.predictions_s3_uri,
        prediction_rows=result.prediction_rows,
        validated_costumers=result.validated_costumers,
    )
    return result


def main() -> int:
    """Configure logging and run the model prediction pipeline."""
    ModelRunnerLogger.configure()

    try:
        result = run_prediction_pipeline()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("prediction_pipeline_failed")
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
