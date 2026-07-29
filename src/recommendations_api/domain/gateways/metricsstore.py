"""Persistent storage for recommendations API metrics."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import boto3
from boto3.dynamodb.types import TypeDeserializer

from recommendations_api.domain.utils.apilogger import ApiLogger

COUNTER_PK = "counter"
LATENCY_PK = "latency"
REQUESTS_COUNTER = "requests_total"
ERRORS_COUNTER = "errors_total"
COLD_START_COUNTER = "cold_start_total"
MAX_LATENCY_OBSERVATIONS = 5000
LATENCY_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class MetricsSnapshot:
    """Aggregated metrics loaded from persistent storage."""

    requests_total: int
    errors_total: int
    cold_start_total: int
    latencies_ms: tuple[float, ...]

    @property
    def latency_count(self) -> int:
        return len(self.latencies_ms)

    @property
    def latency_sum(self) -> float:
        return float(sum(self.latencies_ms))

    @property
    def latency_avg(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return self.latency_sum / self.latency_count

    def latency_quantile(self, pct: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        if len(ordered) == 1:
            return float(ordered[0])
        rank = (pct / 100) * (len(ordered) - 1)
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        weight = rank - lower
        return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


class MetricsStore(Protocol):
    """Contract for persisting and loading API metrics."""

    def record_request(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        """Persist one completed recommendation request."""

    def load_snapshot(self) -> MetricsSnapshot:
        """Load the current aggregated metrics snapshot."""


class InMemoryMetricsStore:
    """In-memory metrics store used by tests and local development."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests_total = 0
        self._errors_total = 0
        self._cold_start_total = 0
        self._latencies_ms: list[float] = []

    def record_request(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        with self._lock:
            self._requests_total += 1
            if is_error:
                self._errors_total += 1
            if is_cold_start:
                self._cold_start_total += 1
            self._latencies_ms.append(latency_ms)
            if len(self._latencies_ms) > MAX_LATENCY_OBSERVATIONS:
                self._latencies_ms = self._latencies_ms[-MAX_LATENCY_OBSERVATIONS:]

    def load_snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                requests_total=self._requests_total,
                errors_total=self._errors_total,
                cold_start_total=self._cold_start_total,
                latencies_ms=tuple(self._latencies_ms),
            )


class DynamoDBMetricsStore:
    """Persist API metrics in DynamoDB for cross-task durability."""

    def __init__(
        self,
        *,
        table_name: str | None = None,
        region_name: str | None = None,
        dynamodb_client: Any | None = None,
    ) -> None:
        resolved_table = (table_name or os.getenv("METRICS_DYNAMODB_TABLE", "")).strip()
        if not resolved_table:
            raise ValueError("METRICS_DYNAMODB_TABLE is required")

        self.table_name = resolved_table
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.dynamodb_client = dynamodb_client or boto3.client(
            "dynamodb",
            region_name=self.region_name,
        )
        self._deserializer = TypeDeserializer()
        self.logger = ApiLogger(self.__class__.__name__)
        self.logger.info(
            "metrics_store_initialized",
            table_name=self.table_name,
            region=self.region_name,
        )

    def record_request(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        self._increment_counter(REQUESTS_COUNTER, 1)
        if is_error:
            self._increment_counter(ERRORS_COUNTER, 1)
        if is_cold_start:
            self._increment_counter(COLD_START_COUNTER, 1)
        self._store_latency_observation(latency_ms)

    def load_snapshot(self) -> MetricsSnapshot:
        counters = self._load_counters()
        latencies = self._load_latencies()
        return MetricsSnapshot(
            requests_total=counters.get(REQUESTS_COUNTER, 0),
            errors_total=counters.get(ERRORS_COUNTER, 0),
            cold_start_total=counters.get(COLD_START_COUNTER, 0),
            latencies_ms=tuple(latencies),
        )

    def _increment_counter(self, counter_name: str, amount: int) -> None:
        self.dynamodb_client.update_item(
            TableName=self.table_name,
            Key={
                "pk": {"S": COUNTER_PK},
                "sk": {"S": counter_name},
            },
            UpdateExpression="ADD #value :amount",
            ExpressionAttributeNames={"#value": "value"},
            ExpressionAttributeValues={":amount": {"N": str(amount)}},
        )

    def _store_latency_observation(self, latency_ms: float) -> None:
        now_ms = int(time.time() * 1000)
        observation_id = uuid.uuid4().hex[:12]
        expires_at = int(time.time()) + LATENCY_TTL_SECONDS
        self.dynamodb_client.put_item(
            TableName=self.table_name,
            Item={
                "pk": {"S": LATENCY_PK},
                "sk": {"S": f"obs#{now_ms:013d}#{observation_id}"},
                "latency_ms": {"N": str(latency_ms)},
                "expires_at": {"N": str(expires_at)},
            },
        )

    def _load_counters(self) -> dict[str, int]:
        response = self.dynamodb_client.batch_get_item(
            RequestItems={
                self.table_name: {
                    "Keys": [
                        {"pk": {"S": COUNTER_PK}, "sk": {"S": REQUESTS_COUNTER}},
                        {"pk": {"S": COUNTER_PK}, "sk": {"S": ERRORS_COUNTER}},
                        {"pk": {"S": COUNTER_PK}, "sk": {"S": COLD_START_COUNTER}},
                    ]
                }
            }
        )

        counters: dict[str, int] = {}
        items = response.get("Responses", {}).get(self.table_name, [])
        for item in items:
            native = self._deserialize_item(item)
            counters[str(native["sk"])] = int(native.get("value", 0))
        return counters

    def _load_latencies(self) -> list[float]:
        latencies: list[float] = []
        query_kwargs: dict[str, Any] = {
            "TableName": self.table_name,
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": {"S": LATENCY_PK}},
            "ScanIndexForward": False,
        }

        while len(latencies) < MAX_LATENCY_OBSERVATIONS:
            response = self.dynamodb_client.query(**query_kwargs)
            for item in response.get("Items", []):
                native = self._deserialize_item(item)
                latencies.append(float(native["latency_ms"]))
                if len(latencies) >= MAX_LATENCY_OBSERVATIONS:
                    break

            last_key = response.get("LastEvaluatedKey")
            if not last_key or len(latencies) >= MAX_LATENCY_OBSERVATIONS:
                break
            query_kwargs["ExclusiveStartKey"] = last_key

        return sorted(latencies)[-MAX_LATENCY_OBSERVATIONS:]

    def _deserialize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        native: dict[str, Any] = {}
        for key, value in item.items():
            decoded = self._deserializer.deserialize(value)
            if isinstance(decoded, Decimal):
                native[key] = float(decoded) if "." in str(decoded) else int(decoded)
            else:
                native[key] = decoded
        return native


def build_metrics_store(store: MetricsStore | None = None) -> MetricsStore:
    """Return an explicit store or build one from environment variables."""
    if store is not None:
        return store
    table_name = os.getenv("METRICS_DYNAMODB_TABLE", "").strip()
    if table_name:
        return DynamoDBMetricsStore(table_name=table_name)
    return InMemoryMetricsStore()
