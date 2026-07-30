"""Prometheus and Datadog metrics backed by in-memory storage."""

from __future__ import annotations

import time
from typing import Any, Literal

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    SummaryMetricFamily,
)

from recommendations_api.domain.gateways.metricsstore import (
    MetricsSnapshot,
    MetricsStore,
    build_metrics_store,
)
from recommendations_api.domain.utils.apilogger import ApiLogger


DatadogMetricType = Literal[1, 3]
DEFAULT_DATADOG_TAGS = ("service:recommendations_api",)


def _datadog_point(timestamp: int, value: float) -> dict[str, int | float]:
    """Build one Datadog v2 series point."""
    return {"timestamp": timestamp, "value": value}


def _datadog_series_entry(
    *,
    metric: str,
    metric_type: DatadogMetricType,
    value: float,
    timestamp: int,
    tags: tuple[str, ...] = DEFAULT_DATADOG_TAGS,
) -> dict[str, Any]:
    """Build one Datadog Metrics API v2 series entry."""
    return {
        "metric": metric,
        "type": metric_type,
        "points": [_datadog_point(timestamp, value)],
        "tags": list(tags),
    }


def build_datadog_series(
    snapshot: MetricsSnapshot,
    *,
    timestamp: int | None = None,
    tags: tuple[str, ...] = DEFAULT_DATADOG_TAGS,
) -> list[dict[str, Any]]:
    """Build Datadog Metrics API v2 ``series`` entries from a snapshot."""
    ts = int(time.time()) if timestamp is None else timestamp
    return [
        _datadog_series_entry(
            metric="recommendations_api.requests.total",
            metric_type=1,
            value=float(snapshot.requests_total),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.errors.total",
            metric_type=1,
            value=float(snapshot.errors_total),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.cold_start.total",
            metric_type=1,
            value=float(snapshot.cold_start_total),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.latency.count",
            metric_type=3,
            value=float(snapshot.latency_count),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.latency.sum_ms",
            metric_type=3,
            value=round(snapshot.latency_sum, 2),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.latency.avg_ms",
            metric_type=3,
            value=round(snapshot.latency_avg, 2),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.latency.p50_ms",
            metric_type=3,
            value=round(snapshot.latency_quantile(50), 2),
            timestamp=ts,
            tags=tags,
        ),
        _datadog_series_entry(
            metric="recommendations_api.latency.p95_ms",
            metric_type=3,
            value=round(snapshot.latency_quantile(95), 2),
            timestamp=ts,
            tags=tags,
        ),
    ]


def _snapshot_log_fields(snapshot: MetricsSnapshot) -> dict[str, Any]:
    """Return aggregated metric fields for structured logging."""
    return {
        "requests_total": snapshot.requests_total,
        "errors_total": snapshot.errors_total,
        "cold_start_total": snapshot.cold_start_total,
        "latency_count": snapshot.latency_count,
        "latency_sum_ms": round(snapshot.latency_sum, 2),
        "latency_avg_ms": round(snapshot.latency_avg, 2),
        "latency_p50_ms": round(snapshot.latency_quantile(50), 2),
        "latency_p95_ms": round(snapshot.latency_quantile(95), 2),
    }


class PersistentMetricsCollector:
    """Expose metrics from the in-memory store using prometheus_client."""

    def __init__(self, store: MetricsStore) -> None:
        self.store = store

    def collect(self):
        snapshot = self.store.load_snapshot()

        requests = CounterMetricFamily(
            "recommendations_api_requests_total",
            "Total HTTP requests handled.",
        )
        requests.add_metric([], snapshot.requests_total)
        yield requests

        errors = CounterMetricFamily(
            "recommendations_api_errors_total",
            "Total HTTP errors.",
        )
        errors.add_metric([], snapshot.errors_total)
        yield errors

        cold_start = CounterMetricFamily(
            "recommendations_api_cold_start_total",
            "Total cold-start fallbacks.",
        )
        cold_start.add_metric([], snapshot.cold_start_total)
        yield cold_start

        latency = SummaryMetricFamily(
            "recommendations_api_latency_ms",
            "Request latency in milliseconds.",
        )
        latency.add_metric([], snapshot.latency_count, snapshot.latency_sum)
        latency.add_sample(
            "recommendations_api_latency_ms",
            {"quantile": "0.5"},
            snapshot.latency_quantile(50),
        )
        latency.add_sample(
            "recommendations_api_latency_ms",
            {"quantile": "0.95"},
            snapshot.latency_quantile(95),
        )
        yield latency

        latency_avg = GaugeMetricFamily(
            "recommendations_api_latency_avg_ms",
            "Average request latency.",
        )
        latency_avg.add_metric([], snapshot.latency_avg)
        yield latency_avg


class MetricsCollector:
    """Record recommendation requests and render Prometheus metrics."""

    def __init__(self, store: MetricsStore | None = None) -> None:
        self.store = build_metrics_store(store)
        self.registry = CollectorRegistry()
        self.registry.register(PersistentMetricsCollector(self.store))
        self.logger = ApiLogger(self.__class__.__name__)

    def observe(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        """Persist one completed recommendation request."""
        self.store.record_request(
            latency_ms=latency_ms,
            is_error=is_error,
            is_cold_start=is_cold_start,
        )
        snapshot = self.store.load_snapshot()
        self.logger.info(
            "api_request_metric",
            latency_ms=round(latency_ms, 2),
            is_error=is_error,
            is_cold_start=is_cold_start,
            **_snapshot_log_fields(snapshot),
        )

    def log_snapshot(self, *, source: str) -> None:
        """Emit the current aggregated metrics snapshot to structured logs."""
        self.logger.info(
            "api_metrics_snapshot",
            source=source,
            **_snapshot_log_fields(self.store.load_snapshot()),
        )

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        return generate_latest(self.registry).decode("utf-8")

    def render_datadog(self) -> dict[str, list[dict[str, Any]]]:
        """Render metrics in Datadog Metrics API v2 ``series`` format."""
        return {
            "series": build_datadog_series(self.store.load_snapshot()),
        }

    def render_combined(self) -> dict[str, Any]:
        """Render Prometheus text and Datadog series in one payload."""
        return {
            "prometheus": self.render_prometheus(),
            "datadog": self.render_datadog(),
        }


class Timer:
    """Simple wall-clock timer used by the HTTP layer."""

    def __init__(self) -> None:
        self._started = time.perf_counter()

    def elapsed_ms(self) -> float:
        """Return elapsed milliseconds since construction."""
        return (time.perf_counter() - self._started) * 1000.0


def create_metrics_collector(store: MetricsStore | None = None) -> MetricsCollector:
    """Build a metrics collector from env or an explicit store."""
    return MetricsCollector(store=store)
