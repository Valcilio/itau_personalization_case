"""Unit tests for model_train.domain.gateways.awsconnector."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from model_train.domain.gateways.awsconnector import AwsConnector


@pytest.fixture
def connector() -> AwsConnector:
    with patch("model_train.domain.gateways.awsconnector.boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        yield AwsConnector(region_name="us-east-1")


def test_download_file(connector: AwsConnector, tmp_path: Path) -> None:
    path = connector.download_file("bucket", "key", tmp_path / "file.csv")
    connector.s3_client.download_file.assert_called_once()
    assert path.name == "file.csv"


def test_upload_file(connector: AwsConnector, tmp_path: Path) -> None:
    local = tmp_path / "file.txt"
    local.write_text("x", encoding="utf-8")
    uri = connector.upload_file(local, "bucket", "prefix/file.txt")
    assert uri == "s3://bucket/prefix/file.txt"


def test_download_training_dataset(connector: AwsConnector, tmp_path: Path) -> None:
    paths = connector.download_training_dataset("bucket", "data", tmp_path)
    assert set(paths) == {"events", "products"}


def test_upload_model_directory(connector: AwsConnector, tmp_path: Path) -> None:
    (tmp_path / "model.pkl").write_bytes(b"model")
    (tmp_path / "model_card.json").write_text("{}", encoding="utf-8")
    uri = connector.upload_model_directory(tmp_path, "bucket", "models/v1")
    assert uri.startswith("s3://bucket/models/v1/model.tar.gz")


def test_register_model_package_creates_group_when_missing(connector: AwsConnector) -> None:
    error = ClientError(
        {"Error": {"Code": "ResourceNotFound", "Message": "Not found"}},
        "DescribeModelPackageGroup",
    )
    connector.sagemaker_client.describe_model_package_group.side_effect = error
    connector.sagemaker_client.create_model_package.return_value = {
        "ModelPackageArn": "arn:package"
    }
    arn = connector.register_model_package(
        model_package_group_name="group",
        model_data_url="s3://bucket/model.tar.gz",
        image_uri="image",
        model_name="model",
        description="desc",
    )
    assert arn == "arn:package"
