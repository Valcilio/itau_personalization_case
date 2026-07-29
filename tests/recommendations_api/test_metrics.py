"""Tests for persistent Prometheus metrics."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from prometheus_client.parser import text_string_to_metric_families

from recommendations_api.domain.gateways.metricsstore import (
    DynamoDBMetricsStore,
    InMemoryMetricsStore,
    MetricsSnapshot,
)
from recommendations_api.domain.utils.metrics import MetricsCollector, create_metrics_collector


def _parse_metrics(text: str) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.labels.get("quantile") == "0.5":
                parsed["recommendations_api_latency_ms_p50"] = sample.value
            elif sample.labels.get("quantile") == "0.95":
                parsed["recommendations_api_latency_ms_p95"] = sample.value
            else:
                parsed[sample.name] = sample.value
    return parsed


def test_in_memory_store_aggregates_counters_and_latencies() -> None:
    store = InMemoryMetricsStore()
    store.record_request(latency_ms=10.0)
    store.record_request(latency_ms=20.0, is_error=True, is_cold_start=True)

    snapshot = store.load_snapshot()
    assert snapshot.requests_total == 2
    assert snapshot.errors_total == 1
    assert snapshot.cold_start_total == 1
    assert snapshot.latency_quantile(50) == 15.0


def test_metrics_collector_renders_prometheus_format() -> None:
    collector = create_metrics_collector()
    collector.observe(latency_ms=10.0)
    collector.observe(latency_ms=30.0, is_error=True, is_cold_start=True)

    parsed = _parse_metrics(collector.render_prometheus())
    assert parsed["recommendations_api_requests_total"] == 2
    assert parsed["recommendations_api_errors_total"] == 1
    assert parsed["recommendations_api_cold_start_total"] == 1
    assert parsed["recommendations_api_latency_ms_count"] == 2
    assert parsed["recommendations_api_latency_ms_p50"] == 20.0


def test_metrics_persist_across_collector_instances() -> None:
    store = InMemoryMetricsStore()
    first = MetricsCollector(store=store)
    second = MetricsCollector(store=store)

    first.observe(latency_ms=12.0)
    second.observe(latency_ms=18.0)

    parsed = _parse_metrics(second.render_prometheus())
    assert parsed["recommendations_api_requests_total"] == 2
    assert parsed["recommendations_api_latency_ms_sum"] == 30.0


def test_dynamodb_store_writes_counters_and_latency_observations() -> None:
    client = MagicMock()
    client.batch_get_item.return_value = {
        "Responses": {
            "metrics-table": [
                {"pk": {"S": "counter"}, "sk": {"S": "requests_total"}, "value": {"N": "2"}},
                {"pk": {"S": "counter"}, "sk": {"S": "errors_total"}, "value": {"N": "1"}},
                {
                    "pk": {"S": "counter"},
                    "sk": {"S": "cold_start_total"},
                    "value": {"N": "1"},
                },
            ]
        }
    }
    client.query.return_value = {
        "Items": [
            {"pk": {"S": "latency"}, "sk": {"S": "obs#1#a"}, "latency_ms": {"N": "10"}},
            {"pk": {"S": "latency"}, "sk": {"S": "obs#2#b"}, "latency_ms": {"N": "20"}},
        ]
    }

    store = DynamoDBMetricsStore(
        table_name="metrics-table",
        region_name="us-east-1",
        dynamodb_client=client,
    )
    store.record_request(latency_ms=15.0, is_error=True, is_cold_start=True)

    client.update_item.assert_any_call(
        TableName="metrics-table",
        Key={"pk": {"S": "counter"}, "sk": {"S": "requests_total"}},
        UpdateExpression="ADD #value :amount",
        ExpressionAttributeNames={"#value": "value"},
        ExpressionAttributeValues={":amount": {"N": "1"}},
    )
    client.put_item.assert_called_once()
    snapshot = store.load_snapshot()
    assert snapshot.requests_total == 2
    assert snapshot.errors_total == 1
    assert snapshot.cold_start_total == 1
    assert snapshot.latencies_ms == (10.0, 20.0)


def test_metrics_snapshot_quantiles() -> None:
    snapshot = MetricsSnapshot(
        requests_total=1,
        errors_total=0,
        cold_start_total=0,
        latencies_ms=(10.0, 20.0, 100.0),
    )
    assert snapshot.latency_quantile(50) == 20.0
    assert snapshot.latency_quantile(95) == pytest.approx(92.0)
    assert snapshot.latency_avg == pytest.approx(43.333333333333336)
