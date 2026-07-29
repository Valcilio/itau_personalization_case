"""Helpers for live AWS integration tests (no mocks)."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import boto3
from botocore.exceptions import ClientError
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_DIR = PROJECT_ROOT / "terraform"


def has_aws_credentials() -> bool:
    """Return True when boto3 can resolve caller identity."""
    try:
        boto3.client("sts").get_caller_identity()
        return True
    except Exception:  # noqa: BLE001 - any auth/config error means unavailable
        return False


def load_terraform_outputs() -> dict[str, str]:
    """Load string terraform outputs from the project state."""
    if not TERRAFORM_DIR.is_dir():
        pytest.skip(f"Terraform directory not found: {TERRAFORM_DIR}")

    try:
        completed = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=TERRAFORM_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        pytest.skip(f"Unable to read terraform outputs: {error}")

    raw = json.loads(completed.stdout or "{}")
    outputs: dict[str, str] = {}
    for key, payload in raw.items():
        value = payload.get("value")
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            outputs[key] = json.dumps(value)
        else:
            outputs[key] = str(value)
    if not outputs:
        pytest.skip("Terraform outputs are empty; deploy infrastructure first.")
    return outputs


def integration_run_id() -> str:
    """Build a unique suffix for integration test artifacts."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"integration-{timestamp}-{uuid.uuid4().hex[:8]}"


@contextmanager
def temporary_env(updates: dict[str, str]) -> Iterator[None]:
    """Temporarily set environment variables inside a test."""
    previous: dict[str, str | None] = {}
    for key, value in updates.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def model_train_env(outputs: dict[str, str], run_id: str) -> dict[str, str]:
    """Environment for ``model_train.run_training_pipeline``."""
    return {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "IMAGE_TAG": run_id,
        "DATA_BUCKET": outputs["data_bucket_name"],
        "DATA_PREFIX": os.getenv("DATA_PREFIX", "training-data"),
        "MODEL_BUCKET": outputs["models_bucket_name"],
        "MODEL_PREFIX": f"models/purchase_propensity/{run_id}",
        "MODEL_OUTPUT_DIR": f"/tmp/model-train-{run_id}",
        "TRAINING_DATA_DIR": f"/tmp/training-data-{run_id}",
        "MODEL_PACKAGE_GROUP_NAME": outputs["model_package_group_name"],
        "INFERENCE_IMAGE_URI": outputs["model_train_image_uri"],
        "LOG_LEVEL": "INFO",
    }


def model_predict_env(outputs: dict[str, str], run_id: str) -> dict[str, str]:
    """Environment for ``model_predict.run_prediction_pipeline``."""
    return {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "DATA_BUCKET": outputs["data_bucket_name"],
        "DATA_PREFIX": os.getenv("DATA_PREFIX", "training-data"),
        "PREDICTIONS_BUCKET": outputs["data_bucket_name"],
        "PREDICTIONS_PREFIX": os.getenv("PREDICTIONS_PREFIX", "predictions"),
        "PREDICTIONS_DYNAMODB_TABLE": outputs["predictions_dynamodb_table_name"],
        "MODEL_PACKAGE_GROUP_NAME": outputs["model_package_group_name"],
        "LOCAL_DATA_DIR": f"/tmp/predict-data-{run_id}",
        "LOCAL_MODEL_DIR": f"/tmp/predict-model-{run_id}",
        "LOCAL_OUTPUT_DIR": f"/tmp/predict-output-{run_id}",
        "LOG_LEVEL": "INFO",
    }


def recommendations_api_env(outputs: dict[str, str]) -> dict[str, str]:
    """Environment for the recommendations API live AWS connectors."""
    return {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "DATA_BUCKET": outputs["data_bucket_name"],
        "DATA_PREFIX": os.getenv("DATA_PREFIX", "training-data"),
        "PREDICTIONS_DYNAMODB_TABLE": outputs["predictions_dynamodb_table_name"],
        "METRICS_DYNAMODB_TABLE": outputs["api_metrics_dynamodb_table_name"],
        "LOG_LEVEL": "INFO",
    }


def s3_object_exists(s3_uri: str) -> bool:
    """Return True when an ``s3://`` object exists."""
    if not s3_uri.startswith("s3://"):
        return Path(s3_uri).exists()
    _, _, remainder = s3_uri.partition("s3://")
    bucket, _, key = remainder.partition("/")
    client = boto3.client("s3")
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def dynamodb_table_has_items(table_name: str) -> bool:
    """Return True when a DynamoDB table contains at least one item."""
    client = boto3.client("dynamodb")
    response = client.scan(TableName=table_name, Limit=1)
    return bool(response.get("Items"))
