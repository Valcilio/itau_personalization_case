"""AWS integration gateway for the recommendations API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from io import StringIO
from typing import Any

import boto3
import pandas as pd
from boto3.dynamodb.types import TypeDeserializer

from recommendations_api.domain.utils.apilogger import ApiLogger


@dataclass(frozen=True)
class AwsConnectorConfig:
    """Runtime configuration for ``AwsConnector``."""

    region_name: str
    predictions_table: str
    data_bucket: str
    data_prefix: str


class AwsConnector:
    """Handle AWS reads required by the recommendations API.

    Responsibilities include querying the predictions DynamoDB table and loading
    the products catalog from S3 for cold-start fallback and category enrichment.
    """

    def __init__(
        self,
        region_name: str | None = None,
        predictions_table: str | None = None,
        data_bucket: str | None = None,
        data_prefix: str | None = None,
    ) -> None:
        """Initialize AWS clients and runtime configuration.

        Args:
            region_name: Optional AWS region.
            predictions_table: DynamoDB table with the latest prediction snapshot.
            data_bucket: S3 bucket containing products.csv.
            data_prefix: S3 prefix for training/prediction source data.
        """
        resolved_table = (
            predictions_table or os.getenv("PREDICTIONS_DYNAMODB_TABLE", "")
        ).strip()
        resolved_bucket = (data_bucket or os.getenv("DATA_BUCKET", "")).strip()
        if not resolved_table:
            raise ValueError("PREDICTIONS_DYNAMODB_TABLE is required")
        if not resolved_bucket:
            raise ValueError("DATA_BUCKET is required")

        self.config = AwsConnectorConfig(
            region_name=region_name or os.getenv("AWS_REGION", "us-east-1"),
            predictions_table=resolved_table,
            data_bucket=resolved_bucket,
            data_prefix=(
                data_prefix or os.getenv("DATA_PREFIX", "training-data")
            ).rstrip("/"),
        )
        self.dynamodb_client = boto3.client(
            "dynamodb",
            region_name=self.config.region_name,
        )
        self.s3_client = boto3.client("s3", region_name=self.config.region_name)
        self._deserializer = TypeDeserializer()
        self.logger = ApiLogger(self.__class__.__name__)
        self.logger.info(
            "aws_connector_initialized",
            region=self.config.region_name,
            predictions_table=self.config.predictions_table,
            data_bucket=self.config.data_bucket,
        )

    def _deserialize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Convert a DynamoDB item into native Python types."""
        native: dict[str, Any] = {}
        for key, value in item.items():
            decoded = self._deserializer.deserialize(value)
            if isinstance(decoded, Decimal):
                native[key] = float(decoded) if "." in str(decoded) else int(decoded)
            else:
                native[key] = decoded
        return native

    def _filter_predictions_for_user(
        self,
        predictions: pd.DataFrame,
        user_id: str,
    ) -> pd.DataFrame:
        """Keep only rows belonging to the requested user."""
        if predictions.empty or "user_id" not in predictions.columns:
            return predictions
        filtered = predictions[predictions["user_id"] == user_id].copy()
        if len(filtered) != len(predictions):
            self.logger.warning(
                "dynamodb_user_rows_filtered",
                user_id=user_id,
                kept_rows=len(filtered),
                dropped_rows=len(predictions) - len(filtered),
            )
        return filtered.reset_index(drop=True)

    def get_user_predictions(self, user_id: str) -> pd.DataFrame:
        """Query all prediction rows for a user from DynamoDB.

        Args:
            user_id: Target user identifier.

        Returns:
            Dataframe with prediction rows (possibly empty).
        """
        self.logger.info("dynamodb_user_query_started", user_id=user_id)
        items: list[dict[str, Any]] = []
        query_kwargs: dict[str, Any] = {
            "TableName": self.config.predictions_table,
            "KeyConditionExpression": "user_id = :user_id",
            "ExpressionAttributeValues": {":user_id": {"S": user_id}},
        }
        while True:
            response = self.dynamodb_client.query(**query_kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query_kwargs["ExclusiveStartKey"] = last_key

        frame = pd.DataFrame([self._deserialize_item(item) for item in items])
        if not frame.empty:
            frame = self._enrich_with_categories(frame)
        frame = self._filter_predictions_for_user(frame, user_id)
        self.logger.info(
            "dynamodb_user_query_completed",
            user_id=user_id,
            rows=len(frame),
        )
        return frame

    def get_cold_start_predictions(self, limit: int) -> pd.DataFrame:
        """Build cold-start recommendations from the products catalog.

        Unknown users receive the most popular products, with
        ``recommendation_score`` set to ``popularity_score``.

        Args:
            limit: Maximum number of products to return.

        Returns:
            Cold-start recommendation dataframe.
        """
        products = self.get_products_catalog()
        cold_start = (
            products.sort_values("popularity_score", ascending=False)
            .head(limit)
            .copy()
        )
        # OBS3: cold-start score is the popularity score.
        cold_start["recommendation_score"] = cold_start["popularity_score"].astype(float)
        cold_start["user_id"] = "cold_start"
        cold_start["is_cold_start"] = True
        cold_start["interactions"] = 0
        cold_start["user_affinity_match"] = 0
        columns = [
            "user_id",
            "product_id",
            "is_cold_start",
            "interactions",
            "price",
            "avg_rating",
            "popularity_score",
            "user_affinity_match",
            "recommendation_score",
            "category",
        ]
        result = cold_start[columns].reset_index(drop=True)
        self.logger.info("cold_start_predictions_built", rows=len(result), limit=limit)
        return result

    @lru_cache(maxsize=1)
    def get_products_catalog(self) -> pd.DataFrame:
        """Download and cache ``products.csv`` from S3."""
        key = f"{self.config.data_prefix}/products.csv"
        self.logger.info(
            "products_catalog_download_started",
            bucket=self.config.data_bucket,
            key=key,
        )
        obj = self.s3_client.get_object(Bucket=self.config.data_bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        products = pd.read_csv(StringIO(body))
        self.logger.info("products_catalog_download_completed", rows=len(products))
        return products

    def _enrich_with_categories(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """Attach product categories when missing from the DynamoDB snapshot."""
        if "category" in predictions.columns:
            return predictions
        products = self.get_products_catalog()[["product_id", "category"]]
        return predictions.merge(products, on="product_id", how="left")
