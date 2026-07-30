"""AWS integration gateway for the model training pipeline."""

import os
import tarfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


class AwsConnector:
    """Handle AWS integrations required by the training pipeline.

    Responsibilities include downloading training datasets from S3, uploading
    model artifacts back to S3 and registering approved model packages in the
    SageMaker Model Registry.
    """

    def __init__(self, region_name: str | None = None) -> None:
        """Initialize AWS clients for the configured region.

        Args:
            region_name: Optional AWS region. Defaults to ``AWS_REGION`` env var.
        """
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.s3_client = boto3.client("s3", region_name=self.region_name)
        self.sagemaker_client = boto3.client("sagemaker", region_name=self.region_name)
        self.logger = ModelTrainerLogger(self.__class__.__name__)
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

    def download_training_dataset(
        self,
        bucket: str,
        prefix: str,
        local_dir: str | Path,
    ) -> dict[str, Path]:
        """Download the events and products CSV files used for training.

        Args:
            bucket: S3 bucket containing the training snapshot.
            prefix: Prefix where ``events.csv`` and ``products.csv`` are stored.
            local_dir: Local directory where the files will be saved.

        Returns:
            Dictionary with local paths for ``events`` and ``products``.
        """
        base_prefix = prefix.rstrip("/")
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "training_dataset_download_started",
            bucket=bucket,
            prefix=base_prefix,
            local_dir=str(local_directory),
        )

        events_key = f"{base_prefix}/events.csv"
        products_key = f"{base_prefix}/products.csv"

        events_path = self.download_file(
            bucket,
            events_key,
            local_directory / "events.csv",
        )
        products_path = self.download_file(
            bucket,
            products_key,
            local_directory / "products.csv",
        )

        self.logger.info(
            "training_dataset_download_completed",
            events_path=str(events_path),
            products_path=str(products_path),
        )

        return {
            "events": events_path,
            "products": products_path,
        }

    def upload_model_directory(self, local_dir: str | Path, bucket: str, prefix: str) -> str:
        """Upload model artifacts to S3, including a SageMaker-compatible tar.gz archive.

        Args:
            local_dir: Directory containing model artifacts.
            bucket: Destination S3 bucket.
            prefix: Destination prefix inside the bucket.

        Returns:
            S3 URI of the ``model.tar.gz`` archive used by SageMaker Model Registry.

        Raises:
            FileNotFoundError: If the directory does not contain files to upload.
        """
        local_directory = Path(local_dir)
        base_prefix = prefix.rstrip("/")
        artifact_files = [
            file_path
            for file_path in local_directory.iterdir()
            if file_path.is_file() and file_path.name != "model.tar.gz"
        ]

        self.logger.info(
            "model_directory_upload_started",
            local_dir=str(local_directory),
            bucket=bucket,
            prefix=base_prefix,
        )

        if not artifact_files:
            self.logger.error(
                "model_directory_upload_failed",
                reason="no_files_found",
                local_dir=str(local_directory),
            )
            raise FileNotFoundError(f"No model files found in {local_directory}")

        uploaded_uris: list[str] = []
        for file_path in artifact_files:
            object_key = f"{base_prefix}/{file_path.name}"
            uploaded_uris.append(self.upload_file(file_path, bucket, object_key))

        archive_path = local_directory / "model.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for file_path in artifact_files:
                archive.add(file_path, arcname=file_path.name)

        archive_uri = self.upload_file(archive_path, bucket, f"{base_prefix}/model.tar.gz")

        self.logger.info(
            "model_directory_upload_completed",
            uploaded_files=len(uploaded_uris) + 1,
            model_archive_s3_uri=archive_uri,
        )
        return archive_uri

    def register_model_package(
        self,
        model_package_group_name: str,
        model_data_url: str,
        image_uri: str,
        model_name: str,
        description: str,
    ) -> str:
        """Register an approved model package in SageMaker Model Registry.

        Args:
            model_package_group_name: Target model package group.
            model_data_url: S3 URI pointing to the serialized model artifact.
            image_uri: Inference image used to serve the model.
            model_name: Business name stored as customer metadata.
            description: Human-readable package description.

        Returns:
            ARN of the created model package.
        """
        self.logger.info(
            "model_registry_registration_started",
            model_package_group_name=model_package_group_name,
            model_data_url=model_data_url,
            model_name=model_name,
        )
        self._ensure_model_package_group(model_package_group_name)

        response = self.sagemaker_client.create_model_package(
            ModelPackageGroupName=model_package_group_name,
            ModelPackageDescription=description,
            ModelApprovalStatus="Approved",
            InferenceSpecification={
                "Containers": [
                    {
                        "Image": image_uri,
                        "ModelDataUrl": model_data_url,
                    }
                ],
                "SupportedContentTypes": ["application/json"],
                "SupportedResponseMIMETypes": ["application/json"],
            },
            CustomerMetadataProperties={
                "model_name": model_name,
            },
        )
        model_package_arn = response["ModelPackageArn"]
        self.logger.info(
            "model_registry_registration_completed",
            model_package_arn=model_package_arn,
        )
        return model_package_arn

    def has_model_packages(self, model_package_group_name: str) -> bool:
        """Return True when the model package group already has at least one version."""
        response = self.sagemaker_client.list_model_packages(
            ModelPackageGroupName=model_package_group_name,
            SortBy="CreationTime",
            SortOrder="Ascending",
            MaxResults=1,
        )
        has_packages = bool(response.get("ModelPackageSummaryList"))
        self.logger.info(
            "model_package_group_versions_checked",
            model_package_group_name=model_package_group_name,
            has_packages=has_packages,
        )
        return has_packages

    def has_model_package_version(
        self,
        model_package_group_name: str,
        model_package_version: int,
    ) -> bool:
        """Return True when the group contains the requested package version."""
        response = self.sagemaker_client.list_model_packages(
            ModelPackageGroupName=model_package_group_name,
            SortBy="CreationTime",
            SortOrder="Ascending",
            MaxResults=100,
        )
        has_version = any(
            item.get("ModelPackageVersion") == model_package_version
            for item in response.get("ModelPackageSummaryList", [])
        )
        self.logger.info(
            "model_package_version_checked",
            model_package_group_name=model_package_group_name,
            model_package_version=model_package_version,
            has_version=has_version,
        )
        return has_version

    def _ensure_model_package_group(self, model_package_group_name: str) -> None:
        """Create the model package group when it does not exist yet."""
        try:
            self.sagemaker_client.describe_model_package_group(
                ModelPackageGroupName=model_package_group_name,
            )
            self.logger.info(
                "model_package_group_found",
                model_package_group_name=model_package_group_name,
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFound":
                self.logger.exception(
                    "model_package_group_lookup_failed",
                    model_package_group_name=model_package_group_name,
                )
                raise
            self.logger.info(
                "model_package_group_creation_started",
                model_package_group_name=model_package_group_name,
            )
            self.sagemaker_client.create_model_package_group(
                ModelPackageGroupName=model_package_group_name,
                ModelPackageGroupDescription=(
                    "Purchase propensity models generated by the training pipeline."
                ),
            )
            self.logger.info(
                "model_package_group_creation_completed",
                model_package_group_name=model_package_group_name,
            )
