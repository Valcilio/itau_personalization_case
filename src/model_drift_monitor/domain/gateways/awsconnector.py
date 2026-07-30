"""AWS integration gateway for the model drift monitor."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pandas as pd

from model_drift_monitor.domain.utils.modeldriftlogger import ModelDriftLogger


class AwsConnector:
    """Handle AWS reads/writes and ECS/SNS side effects for drift monitoring."""

    def __init__(self, region_name: str | None = None) -> None:
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.s3_client = boto3.client("s3", region_name=self.region_name)
        self.ecs_client = boto3.client("ecs", region_name=self.region_name)
        self.sns_client = boto3.client("sns", region_name=self.region_name)
        self.logger = ModelDriftLogger(self.__class__.__name__)

    def download_file(self, bucket: str, key: str, local_path: str | Path) -> Path:
        """Download a single object from S3."""
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info("s3_download_started", bucket=bucket, key=key)
        self.s3_client.download_file(bucket, key, str(destination))
        return destination

    def upload_file(self, local_path: str | Path, bucket: str, key: str) -> str:
        """Upload a local file to S3 and return its URI."""
        self.s3_client.upload_file(str(local_path), bucket, key)
        s3_uri = f"s3://{bucket}/{key}"
        self.logger.info("s3_upload_completed", bucket=bucket, key=key, s3_uri=s3_uri)
        return s3_uri

    @staticmethod
    def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
        """Split an S3 URI into bucket and key."""
        parsed = urlparse(s3_uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URI: {s3_uri}")
        return bucket, key

    def download_prediction_dataset(
        self,
        bucket: str,
        prefix: str,
        local_dir: str | Path,
    ) -> dict[str, Path]:
        """Download events.csv and products.csv used for ground truth and drift."""
        base_prefix = prefix.rstrip("/")
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)
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
        return {"events": events_path, "products": products_path}

    def load_predictions_csv(self, s3_uri: str, local_dir: str | Path) -> pd.DataFrame:
        """Download and load a prediction snapshot from S3."""
        bucket, key = self.parse_s3_uri(s3_uri)
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)
        filename = Path(key).name
        local_path = self.download_file(bucket, key, local_directory / filename)
        return pd.read_csv(local_path)

    def upload_monitoring_report(
        self,
        report: pd.DataFrame,
        bucket: str,
        prefix: str,
        filename: str,
        local_dir: str | Path,
    ) -> str:
        """Persist monitoring metrics as parquet in S3."""
        local_directory = Path(local_dir)
        local_directory.mkdir(parents=True, exist_ok=True)
        local_path = local_directory / filename
        report.to_parquet(local_path, index=False)
        object_key = f"{prefix.rstrip('/')}/{filename}"
        return self.upload_file(local_path, bucket, object_key)

    def run_model_train_task(self) -> dict:
        """Launch a one-off model_train ECS Fargate task."""
        cluster = os.getenv("MODEL_TRAIN_CLUSTER", "").strip()
        task_definition = os.getenv("MODEL_TRAIN_TASK_DEFINITION", "").strip()
        subnets = [
            subnet.strip()
            for subnet in os.getenv("MODEL_TRAIN_SUBNETS", "").split(",")
            if subnet.strip()
        ]
        security_groups = [
            security_group.strip()
            for security_group in os.getenv("MODEL_TRAIN_SECURITY_GROUP", "").split(",")
            if security_group.strip()
        ]

        if not cluster or not task_definition or not subnets or not security_groups:
            raise ValueError(
                "MODEL_TRAIN_CLUSTER, MODEL_TRAIN_TASK_DEFINITION, "
                "MODEL_TRAIN_SUBNETS and MODEL_TRAIN_SECURITY_GROUP are required"
            )

        self.logger.info(
            "ecs_run_task_started",
            cluster=cluster,
            task_definition=task_definition,
        )
        response = self.ecs_client.run_task(
            cluster=cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": security_groups,
                    "assignPublicIp": "ENABLED",
                }
            },
        )
        failures = response.get("failures", [])
        if failures:
            raise RuntimeError(f"Failed to start model_train task: {failures}")
        return response.get("tasks", [{}])[0]

    def publish_drift_notification(
        self,
        topic_arn: str,
        subject: str,
        payload: dict,
    ) -> str:
        """Publish a drift or retrain notification to SNS."""
        if not topic_arn:
            self.logger.info("sns_notification_skipped", reason="topic_not_configured")
            return ""

        message = json.dumps(payload, ensure_ascii=False, indent=2)
        response = self.sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject[:100],
            Message=message,
        )
        message_id = response.get("MessageId", "")
        self.logger.info("sns_notification_published", topic_arn=topic_arn, message_id=message_id)
        return message_id
