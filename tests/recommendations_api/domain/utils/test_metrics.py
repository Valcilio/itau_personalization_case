"""Unit tests for recommendations_api.domain.utils.metrics."""

import logging
import time
from unittest.mock import patch

from prometheus_client.parser import text_string_to_metric_families

from recommendations_api.domain.gateways.metricsstore import InMemoryMetricsStore
from recommendations_api.domain.utils.apilogger import ApiLogger
from recommendations_api.domain.utils.metrics import (
    MetricsCollector,
    PersistentMetricsCollector,
    Timer,
    build_datadog_series,
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


def test_metrics_collector_observe_and_render(capsys) -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure()

    collector = create_metrics_collector()
    collector.observe(latency_ms=10.0)
    collector.observe(latency_ms=30.0, is_error=True, is_cold_start=True)
    parsed = _parse_metrics(collector.render_prometheus())
    assert parsed["recommendations_api_requests_total"] == 2
    assert parsed["recommendations_api_errors_total"] == 1

    output = capsys.readouterr().out
    assert "api_request_metric" in output
    assert '"requests_total": 2' in output


def test_metrics_collector_log_snapshot(capsys) -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure()

    collector = create_metrics_collector()
    collector.observe(latency_ms=12.0)
    collector.log_snapshot(source="test")
    output = capsys.readouterr().out
    assert "api_metrics_snapshot" in output
    assert '"source": "test"' in output
    assert '"latency_p50_ms": 12.0' in output


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


def test_build_datadog_series_uses_v2_shape() -> None:
    store = InMemoryMetricsStore()
    store.record_request(latency_ms=10.0)
    store.record_request(latency_ms=30.0, is_error=True, is_cold_start=True)
    series = build_datadog_series(store.load_snapshot(), timestamp=1_700_000_000)

    assert len(series) == 8
    requests = next(item for item in series if item["metric"].endswith("requests.total"))
    assert requests == {
        "metric": "recommendations_api.requests.total",
        "type": 1,
        "points": [{"timestamp": 1_700_000_000, "value": 2.0}],
        "tags": ["service:recommendations_api"],
    }
    p95 = next(item for item in series if item["metric"].endswith("latency.p95_ms"))
    assert p95["type"] == 3
    assert p95["points"][0]["value"] == round(
        store.load_snapshot().latency_quantile(95), 2
    )


def test_metrics_collector_render_datadog_and_combined() -> None:
    collector = create_metrics_collector()
    collector.observe(latency_ms=12.0)

    datadog = collector.render_datadog()
    assert "series" in datadog
    assert datadog["series"][0]["metric"] == "recommendations_api.requests.total"

    combined = collector.render_combined()
    assert "prometheus" in combined
    assert "datadog" in combined
    assert "recommendations_api_requests_total" in combined["prometheus"]
