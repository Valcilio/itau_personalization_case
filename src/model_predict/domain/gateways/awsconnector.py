"""AWS integration gateway for the model prediction pipeline."""

import os
import tarfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pandas as pd
from boto3.dynamodb.types import TypeSerializer

from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


class AwsConnector:
    """Handle AWS integrations required by the prediction pipeline.

    Responsibilities include downloading events/products from S3, retrieving the
    hardcoded SageMaker model package version, downloading its artifact,
    uploading versioned prediction outputs to S3 and replacing DynamoDB contents
    with the latest prediction snapshot.
    """

    HARDCODED_MODEL_PACKAGE_VERSION = 1
    DYNAMODB_BATCH_SIZE = 25

    def __init__(self, region_name: str | None = None) -> None:
        """Initialize AWS clients for the configured region.

        Args:
            region_name: Optional AWS region. Defaults to ``AWS_REGION`` env var.
        """
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.s3_client = boto3.client("s3", region_name=self.region_name)
        self.sagemaker_client = boto3.client("sagemaker", region_name=self.region_name)
        self.dynamodb_client = boto3.client("dynamodb", region_name=self.region_name)
        self._serializer = TypeSerializer()
        self.logger = ModelRunnerLogger(self.__class__.__name__)
        self.logger.info("aws_connector_initialized", region=self.region_name)

    def download_file(self, bucket: str, key: str, local_path: str | Path) -> Path:
        """Download a single object from S3.

        Args:
            bucket: Source S3 bucket.
            key: Object key inside the bucket.
            local_path: Local destination path.

        Returns:
            Path to the downloaded file.
        """
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info(
            "s3_download_started",
            bucket=bucket,
            key=key,
            destination=str(destination),
        )
        self.s3_client.download_file(bucket, key, str(destination))
        self.logger.info(
            "s3_download_completed",
            bucket=bucket,
            key=key,
            destination=str(destination),
        )
        return destination

    def upload_file(self, local_path: str | Path, bucket: str, key: str) -> str:
        """Upload a local file to S3.

        Args:
            local_path: File available on disk.
            bucket: Destination S3 bucket.
            key: Destination object key.

        Returns:
            S3 URI for the uploaded object.
        """
        self.logger.info("s3_upload_started", bucket=bucket, key=key, source=str(local_path))
        self.s3_client.upload_file(str(local_path), bucket, key)
        s3_uri = f"s3://{bucket}/{key}"
        self.logger.info("s3_upload_completed", bucket=bucket, key=key, s3_uri=s3_uri)
        return s3_uri

    def download_prediction_dataset(
        self,
        bucket: str,
        prefix: str,
        local_dir: str | Path,
    ) -> dict[str, Path]:
        """Download the events and products CSV files used for prediction.

        Args:
            bucket: S3 bucket containing the feature source snapshot.
            prefix: Prefix where ``events.csv`` and ``products.csv`` are stored.
            local_dir: Local directory where the files will be saved.

        Returns:
            Dictionary with local paths for ``events`` and ``products``.
        """
        base_prefix = prefix.rstrip("/")
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "prediction_dataset_download_started",
            bucket=bucket,
            prefix=base_prefix,
            local_dir=str(local_directory),
        )

        events_path = self.download_file(
            bucket,
            f"{base_prefix}/events.csv",
            local_directory / "events.csv",
        )
        products_path = self.download_file(
            bucket,
            f"{base_prefix}/products.csv",
            local_directory / "products.csv",
        )

        self.logger.info(
            "prediction_dataset_download_completed",
            events_path=str(events_path),
            products_path=str(products_path),
        )
        return {
            "events": events_path,
            "products": products_path,
        }

    def describe_hardcoded_model_package(
        self,
        model_package_group_name: str,
    ) -> dict:
        """Describe the hardcoded model package version used for inference.

        Args:
            model_package_group_name: SageMaker Model Registry group name.

        Returns:
            Response payload from ``describe_model_package``.
        """
        self.logger.info(
            "model_package_lookup_started",
            model_package_group_name=model_package_group_name,
            model_package_version=self.HARDCODED_MODEL_PACKAGE_VERSION,
        )
        packages = self.sagemaker_client.list_model_packages(
            ModelPackageGroupName=model_package_group_name,
            SortBy="CreationTime",
            SortOrder="Ascending",
            MaxResults=100,
        )
        matching = [
            item
            for item in packages.get("ModelPackageSummaryList", [])
            if item.get("ModelPackageVersion") == self.HARDCODED_MODEL_PACKAGE_VERSION
        ]
        if not matching:
            raise LookupError(
                "Model package version "
                f"{self.HARDCODED_MODEL_PACKAGE_VERSION} not found in group "
                f"{model_package_group_name}"
            )

        model_package_arn = matching[0]["ModelPackageArn"]
        description = self.sagemaker_client.describe_model_package(
            ModelPackageName=model_package_arn,
        )
        self.logger.info(
            "model_package_lookup_completed",
            model_package_arn=model_package_arn,
            model_package_version=self.HARDCODED_MODEL_PACKAGE_VERSION,
        )
        return description

    def download_model_artifact(
        self,
        model_package_group_name: str,
        local_dir: str | Path,
    ) -> Path:
        """Download and extract the artifact for the hardcoded model package.

        Args:
            model_package_group_name: SageMaker Model Registry group name.
            local_dir: Local directory used to store the extracted artifact.

        Returns:
            Path to the directory containing ``model.pkl``.
        """
        description = self.describe_hardcoded_model_package(model_package_group_name)
        containers = description["InferenceSpecification"]["Containers"]
        model_data_url = containers[0]["ModelDataUrl"]

        parsed = urlparse(model_data_url)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)
        archive_path = local_directory / "model.tar.gz"
        extract_dir = local_directory / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "model_artifact_download_started",
            model_data_url=model_data_url,
            destination=str(archive_path),
        )
        self.download_file(bucket, key, archive_path)

        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir)

        self.logger.info(
            "model_artifact_download_completed",
            extract_dir=str(extract_dir),
            model_data_url=model_data_url,
        )
        return extract_dir

    def upload_predictions(
        self,
        predictions: pd.DataFrame,
        bucket: str,
        prefix: str,
        filename: str,
        local_dir: str | Path,
    ) -> str:
        """Persist prediction outputs locally and upload them to S3.

        Args:
            predictions: Dataframe containing purchase probabilities.
            bucket: Destination S3 bucket.
            prefix: Destination prefix inside the bucket.
            filename: Output file name (must include a unique hash/timestamp).
            local_dir: Local directory used before uploading.

        Returns:
            S3 URI of the uploaded predictions file.
        """
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)
        local_path = local_directory / filename
        predictions.to_csv(local_path, index=False)

        object_key = f"{prefix.rstrip('/')}/{filename}"
        self.logger.info(
            "predictions_upload_started",
            rows=len(predictions),
            local_path=str(local_path),
            bucket=bucket,
            key=object_key,
        )
        return self.upload_file(local_path, bucket, object_key)

    @staticmethod
    def prediction_row_to_item(row: pd.Series) -> dict:
        """Convert a prediction row into a native Python item for DynamoDB.

        Args:
            row: Single formatted prediction row.

        Returns:
            Dictionary ready to be serialized into DynamoDB attribute values.
        """
        return {
            "user_id": str(row["user_id"]),
            "product_id": str(row["product_id"]),
            "is_cold_start": bool(row["is_cold_start"]),
            "interactions": int(row["interactions"]),
            "price": Decimal(str(row["price"])),
            "avg_rating": Decimal(str(row["avg_rating"])),
            "popularity_score": Decimal(str(row["popularity_score"])),
            "user_affinity_match": int(row["user_affinity_match"]),
            "recommendation_score": Decimal(str(row["recommendation_score"])),
        }

    def _serialize_item(self, item: dict) -> dict:
        """Serialize a native item into DynamoDB attribute-value format."""
        return {key: self._serializer.serialize(value) for key, value in item.items()}

    def _scan_all_keys(self, table_name: str) -> list[dict]:
        """Scan every primary key currently stored in the predictions table."""
        keys: list[dict] = []
        scan_kwargs: dict = {
            "TableName": table_name,
            "ProjectionExpression": "user_id, product_id",
        }
        while True:
            response = self.dynamodb_client.scan(**scan_kwargs)
            keys.extend(response.get("Items", []))
            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key
        return keys

    def _batch_write(self, table_name: str, request_items: list[dict]) -> None:
        """Write DynamoDB batch requests, retrying unprocessed items."""
        for offset in range(0, len(request_items), self.DYNAMODB_BATCH_SIZE):
            chunk = request_items[offset : offset + self.DYNAMODB_BATCH_SIZE]
            unprocessed = {table_name: chunk}
            while unprocessed.get(table_name):
                response = self.dynamodb_client.batch_write_item(
                    RequestItems=unprocessed,
                )
                unprocessed = response.get("UnprocessedItems", {})

    def replace_predictions_table(
        self,
        table_name: str,
        predictions: pd.DataFrame,
    ) -> int:
        """Replace the DynamoDB table contents with the latest predictions.

        Existing items are deleted and the new prediction snapshot is written in
        full, so the table always reflects only the latest model_predict run.

        Args:
            table_name: Target DynamoDB table name.
            predictions: Formatted prediction dataframe.

        Returns:
            Number of items written to the table.
        """
        self.logger.info(
            "dynamodb_predictions_replace_started",
            table_name=table_name,
            incoming_rows=len(predictions),
        )

        existing_keys = self._scan_all_keys(table_name)
        if existing_keys:
            delete_requests = [
                {"DeleteRequest": {"Key": key}} for key in existing_keys
            ]
            self._batch_write(table_name, delete_requests)
            self.logger.info(
                "dynamodb_predictions_cleared",
                table_name=table_name,
                deleted_rows=len(existing_keys),
            )

        put_requests = [
            {
                "PutRequest": {
                    "Item": self._serialize_item(self.prediction_row_to_item(row)),
                }
            }
            for _, row in predictions.iterrows()
        ]
        if put_requests:
            self._batch_write(table_name, put_requests)

        self.logger.info(
            "dynamodb_predictions_replace_completed",
            table_name=table_name,
            written_rows=len(put_requests),
        )
        return len(put_requests)
