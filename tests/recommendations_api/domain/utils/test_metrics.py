"""Unit tests for recommendations_api.domain.utils.metrics."""

import time
from unittest.mock import patch

from prometheus_client.parser import text_string_to_metric_families

from recommendations_api.domain.gateways.metricsstore import InMemoryMetricsStore
from recommendations_api.domain.utils.metrics import (
    MetricsCollector,
    PersistentMetricsCollector,
    Timer,
    create_metrics_collector,
)


def _parse_metrics(text: str) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.labels.get("quantile") == "0.5":
                parsed["p50"] = sample.value
            elif sample.labels.get("quantile") == "0.95":
                parsed["p95"] = sample.value
            else:
                parsed[sample.name] = sample.value
    return parsed


def test_timer_elapsed_ms() -> None:
    timer = Timer()
    time.sleep(0.01)
    assert timer.elapsed_ms() >= 10


def test_metrics_collector_observe_and_render() -> None:
    collector = create_metrics_collector()
    collector.observe(latency_ms=10.0)
    collector.observe(latency_ms=30.0, is_error=True, is_cold_start=True)
    parsed = _parse_metrics(collector.render_prometheus())
    assert parsed["recommendations_api_requests_total"] == 2
    assert parsed["recommendations_api_errors_total"] == 1


def test_persistent_metrics_collector_reads_store() -> None:
    store = InMemoryMetricsStore()
    store.record_request(latency_ms=12.0)
    families = list(PersistentMetricsCollector(store).collect())
    assert len(families) == 5


def test_create_metrics_collector_with_custom_store() -> None:
    store = InMemoryMetricsStore()
    collector = MetricsCollector(store=store)
    collector.observe(latency_ms=5.0)
    parsed = _parse_metrics(collector.render_prometheus())
    assert parsed["recommendations_api_requests_total"] == 1
