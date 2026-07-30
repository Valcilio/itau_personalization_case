"""Unit tests for tests.helpers.api_gateway."""

from __future__ import annotations

import pytest

from tests.helpers.api_gateway import (
    assert_datadog_metrics,
    assert_readme_metrics,
    normalize_api_base_url,
    parse_prometheus_metrics,
)


def test_normalize_api_base_url_appends_stage() -> None:
    assert (
        normalize_api_base_url("https://abc.execute-api.us-east-1.amazonaws.com")
        == "https://abc.execute-api.us-east-1.amazonaws.com/v1"
    )


def test_normalize_api_base_url_keeps_existing_stage() -> None:
    url = "https://abc.execute-api.us-east-1.amazonaws.com/v1"
    assert normalize_api_base_url(url) == url


def test_parse_prometheus_metrics_extracts_quantiles() -> None:
    text = """
# HELP recommendations_api_requests_total Total HTTP requests handled.
# TYPE recommendations_api_requests_total counter
recommendations_api_requests_total 3.0
recommendations_api_latency_ms{quantile="0.5"} 10.0
recommendations_api_latency_ms{quantile="0.95"} 20.0
recommendations_api_errors_total 0.0
recommendations_api_cold_start_total 1.0
recommendations_api_latency_avg_ms 12.0
""".strip()
    parsed = parse_prometheus_metrics(text)
    assert parsed["recommendations_api_requests_total"] == 3.0
    assert parsed["recommendations_api_latency_ms_p50"] == 10.0
    assert parsed["recommendations_api_latency_ms_p95"] == 20.0


def test_assert_readme_metrics_accepts_valid_payload() -> None:
    text = """
recommendations_api_requests_total 8.0
recommendations_api_errors_total 1.0
recommendations_api_cold_start_total 2.0
recommendations_api_latency_avg_ms 15.0
recommendations_api_latency_ms{quantile="0.5"} 10.0
recommendations_api_latency_ms{quantile="0.95"} 20.0
""".strip()
    assert_readme_metrics(text, min_requests=6)


def test_assert_datadog_metrics_accepts_valid_payload() -> None:
    payload = {
        "series": [
            {
                "metric": name,
                "type": 1 if name.endswith(".total") else 3,
                "points": [{"timestamp": 1, "value": 1.0}],
                "tags": ["service:recommendations_api"],
            }
            for name in (
                "recommendations_api.requests.total",
                "recommendations_api.errors.total",
                "recommendations_api.cold_start.total",
                "recommendations_api.latency.avg_ms",
                "recommendations_api.latency.p50_ms",
                "recommendations_api.latency.p95_ms",
            )
        ]
    }
    assert_datadog_metrics(payload)
