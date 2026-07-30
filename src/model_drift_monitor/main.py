"""Entrypoint for the model drift monitor batch job."""

import json
import os
import re
import sys
from dataclasses import asdict

import pandas as pd

from model_drift_monitor.domain.gateways.awsconnector import AwsConnector
from model_drift_monitor.domain.gateways.metricshandler import MetricsHandler
from model_drift_monitor.domain.utils.modeldriftlogger import ModelDriftLogger

PREDICTIONS_FILENAME_PATTERN = re.compile(
    r"^predictions_(?P<timestamp>\d{14})_(?P<hash>[a-f0-9]{8})\.csv$"
)


def extract_run_hash(predictions_filename: str) -> str:
    """Extract the short hash embedded in a predictions object name."""
    match = PREDICTIONS_FILENAME_PATTERN.match(predictions_filename)
    if not match:
        raise ValueError(
            "PREDICTIONS_FILENAME must match predictions_<timestamp>_<hash>.csv"
        )
    return match.group("hash")


def load_config() -> dict[str, str]:
    """Load runtime configuration from environment variables."""
    data_bucket = os.getenv("DATA_BUCKET", "").strip()
    predictions_s3_uri = os.getenv("PREDICTIONS_S3_URI", "").strip()
    predictions_filename = os.getenv("PREDICTIONS_FILENAME", "").strip()

    if not data_bucket:
        raise ValueError("DATA_BUCKET is required")
    if not predictions_s3_uri:
        raise ValueError("PREDICTIONS_S3_URI is required")
    if not predictions_filename:
        predictions_filename = predictions_s3_uri.rsplit("/", maxsplit=1)[-1]

    return {
        "data_bucket": data_bucket,
        "data_prefix": os.getenv("DATA_PREFIX", "training-data"),
        "predictions_s3_uri": predictions_s3_uri,
        "predictions_filename": predictions_filename,
        "run_hash": extract_run_hash(predictions_filename),
        "monitoring_bucket": os.getenv("MONITORING_BUCKET", "").strip() or data_bucket,
        "monitoring_prefix": os.getenv("MONITORING_PREFIX", "model-performance"),
        "local_data_dir": os.getenv("LOCAL_DATA_DIR", "/tmp/drift-data"),
        "local_output_dir": os.getenv("LOCAL_OUTPUT_DIR", "/tmp/drift-output"),
        "sns_topic_arn": os.getenv("DRIFT_SNS_TOPIC_ARN", "").strip(),
    }


def run_monitoring_pipeline() -> dict:
    """Execute drift monitoring end to end."""
    config = load_config()
    logger = ModelDriftLogger("main")
    logger.info("drift_monitor_started", predictions_s3_uri=config["predictions_s3_uri"])

    aws_connector = AwsConnector()
    metrics_handler = MetricsHandler(aws_connector=aws_connector)

    dataset_paths = aws_connector.download_prediction_dataset(
        bucket=config["data_bucket"],
        prefix=config["data_prefix"],
        local_dir=config["local_data_dir"],
    )
    events = pd.read_csv(dataset_paths["events"])
    products = pd.read_csv(dataset_paths["products"])
    predictions = aws_connector.load_predictions_csv(
        config["predictions_s3_uri"],
        config["local_data_dir"],
    )

    result = metrics_handler.run(
        predictions=predictions,
        events=events,
        products=products,
        predictions_s3_uri=config["predictions_s3_uri"],
        run_hash=config["run_hash"],
        monitoring_bucket=config["monitoring_bucket"],
        monitoring_prefix=config["monitoring_prefix"],
        local_output_dir=config["local_output_dir"],
        sns_topic_arn=config["sns_topic_arn"],
    )
    return asdict(result)


def main() -> int:
    """Configure logging and run the drift monitor pipeline."""
    ModelDriftLogger.configure()

    try:
        result = run_monitoring_pipeline()
    except Exception:  # pylint: disable=broad-exception-caught
        ModelDriftLogger("main").exception("drift_monitor_failed")
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
