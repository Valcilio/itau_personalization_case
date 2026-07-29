"""Unit tests for recommendations_api.domain.gateways.metricsstore."""

from unittest.mock import MagicMock, patch

import pytest

from recommendations_api.domain.gateways.metricsstore import (
    DynamoDBMetricsStore,
    InMemoryMetricsStore,
    MetricsSnapshot,
    build_metrics_store,
)


def test_metrics_snapshot_properties_and_quantile() -> None:
    snapshot = MetricsSnapshot(
        requests_total=2,
        errors_total=1,
        cold_start_total=1,
        latencies_ms=(10.0, 20.0, 100.0),
    )
    assert snapshot.latency_count == 3
    assert snapshot.latency_sum == 130.0
    assert snapshot.latency_avg == pytest.approx(43.333333333333336)
    assert snapshot.latency_quantile(50) == 20.0


def test_in_memory_store_record_request_and_load_snapshot() -> None:
    store = InMemoryMetricsStore()
    store.record_request(latency_ms=10.0)
    store.record_request(latency_ms=20.0, is_error=True, is_cold_start=True)
    snapshot = store.load_snapshot()
    assert snapshot.requests_total == 2
    assert snapshot.errors_total == 1
    assert snapshot.cold_start_total == 1


def test_build_metrics_store_uses_in_memory_by_default(monkeypatch) -> None:
    monkeypatch.delenv("METRICS_DYNAMODB_TABLE", raising=False)
    store = build_metrics_store()
    assert isinstance(store, InMemoryMetricsStore)


def test_build_metrics_store_uses_dynamodb_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_DYNAMODB_TABLE", "metrics-table")
    with patch("recommendations_api.domain.gateways.metricsstore.boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        store = build_metrics_store()
        assert isinstance(store, DynamoDBMetricsStore)


def test_dynamodb_store_record_request_and_load_snapshot() -> None:
    client = MagicMock()
    client.batch_get_item.return_value = {
        "Responses": {
            "metrics-table": [
                {"pk": {"S": "counter"}, "sk": {"S": "requests_total"}, "value": {"N": "1"}},
            ]
        }
    }
    client.query.return_value = {"Items": []}
    store = DynamoDBMetricsStore(
        table_name="metrics-table",
        region_name="us-east-1",
        dynamodb_client=client,
    )
    store.record_request(latency_ms=15.0)
    snapshot = store.load_snapshot()
    assert snapshot.requests_total == 1
    client.update_item.assert_called()
    client.put_item.assert_called_once()
