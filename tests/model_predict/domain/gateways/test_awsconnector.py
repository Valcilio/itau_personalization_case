"""Unit tests for model_predict.domain.gateways.awsconnector."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from model_predict.domain.gateways.awsconnector import AwsConnector


@pytest.fixture
def connector() -> AwsConnector:
    with patch("model_predict.domain.gateways.awsconnector.boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        yield AwsConnector(region_name="us-east-1")


def test_init_initializes_clients(connector: AwsConnector) -> None:
    assert connector.region_name == "us-east-1"


def test_download_file_creates_parent_and_downloads(connector: AwsConnector, tmp_path: Path) -> None:
    destination = connector.download_file("bucket", "key.csv", tmp_path / "nested/key.csv")
    connector.s3_client.download_file.assert_called_once()
    assert destination == tmp_path / "nested/key.csv"


def test_upload_file_returns_s3_uri(connector: AwsConnector, tmp_path: Path) -> None:
    local_file = tmp_path / "file.csv"
    local_file.write_text("a", encoding="utf-8")
    uri = connector.upload_file(local_file, "bucket", "prefix/file.csv")
    assert uri == "s3://bucket/prefix/file.csv"


def test_download_prediction_dataset_returns_paths(connector: AwsConnector, tmp_path: Path) -> None:
    paths = connector.download_prediction_dataset("bucket", "data", tmp_path)
    assert set(paths.keys()) == {"events", "products"}
    assert connector.s3_client.download_file.call_count == 2


def test_describe_hardcoded_model_package_returns_description(connector: AwsConnector) -> None:
    connector.sagemaker_client.list_model_packages.return_value = {
        "ModelPackageSummaryList": [
            {"ModelPackageArn": "arn:model", "ModelPackageVersion": 1}
        ]
    }
    connector.sagemaker_client.describe_model_package.return_value = {"ok": True}
    description = connector.describe_hardcoded_model_package("group")
    assert description == {"ok": True}


def test_describe_hardcoded_model_package_raises_when_missing(connector: AwsConnector) -> None:
    connector.sagemaker_client.list_model_packages.return_value = {
        "ModelPackageSummaryList": []
    }
    with pytest.raises(LookupError):
        connector.describe_hardcoded_model_package("group")


def test_download_model_artifact_extracts_tar(connector: AwsConnector, tmp_path: Path) -> None:
    connector.sagemaker_client.list_model_packages.return_value = {
        "ModelPackageSummaryList": [
            {"ModelPackageArn": "arn:model", "ModelPackageVersion": 1}
        ]
    }
    connector.sagemaker_client.describe_model_package.return_value = {
        "InferenceSpecification": {
            "Containers": [{"ModelDataUrl": "s3://bucket/model.tar.gz"}]
        }
    }

    archive = tmp_path / "model.tar.gz"
    import tarfile

    with tarfile.open(archive, "w:gz") as tar:
        inner = tmp_path / "model.pkl"
        inner.write_bytes(b"data")
        tar.add(inner, arcname="model.pkl")

    def fake_download(_bucket, _key, local_path):
        Path(local_path).write_bytes(archive.read_bytes())

    connector.s3_client.download_file.side_effect = fake_download
    extract_dir = connector.download_model_artifact("group", tmp_path / "artifact")
    assert (extract_dir / "model.pkl").exists()


def test_upload_predictions_writes_csv_and_uploads(connector: AwsConnector, tmp_path: Path) -> None:
    predictions = pd.DataFrame({"user_id": ["u_1"], "product_id": ["p_1"]})
    uri = connector.upload_predictions(
        predictions=predictions,
        bucket="bucket",
        prefix="predictions",
        filename="predictions_test.csv",
        local_dir=tmp_path,
    )
    assert uri.startswith("s3://bucket/predictions/")


def test_prediction_row_to_item_converts_types() -> None:
    row = pd.Series(
        {
            "user_id": "u_1",
            "product_id": "p_1",
            "is_cold_start": False,
            "interactions": 2,
            "price": 10.5,
            "avg_rating": 4.0,
            "popularity_score": 0.8,
            "user_affinity_match": 1,
            "recommendation_score": 0.91,
        }
    )
    item = AwsConnector.prediction_row_to_item(row)
    assert item["price"] == Decimal("10.5")
    assert item["recommendation_score"] == Decimal("0.91")


def test_replace_predictions_table_writes_new_rows(connector: AwsConnector) -> None:
    connector.dynamodb_client.scan.return_value = {
        "Items": [{"user_id": {"S": "u_1"}, "product_id": {"S": "p_1"}}]
    }
    connector.dynamodb_client.batch_write_item.return_value = {}
    predictions = pd.DataFrame(
        {
            "user_id": ["u_2"],
            "product_id": ["p_2"],
            "is_cold_start": [False],
            "interactions": [1],
            "price": [10.0],
            "avg_rating": [4.0],
            "popularity_score": [0.5],
            "user_affinity_match": [1],
            "recommendation_score": [0.7],
        }
    )
    written = connector.replace_predictions_table("table", predictions)
    assert written == 1
