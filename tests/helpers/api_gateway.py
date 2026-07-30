"""Helpers for live API Gateway smoke tests."""

from __future__ import annotations

import os
from typing import Any

import boto3
import httpx
import pytest

from tests.helpers.aws_integration import require_terraform_output

API_STAGE = "v1"
DEFAULT_KNOWN_USER_ID = "u_0231"
DEFAULT_COLD_START_USER_ID = "u_9999"

EXPECTED_PROMETHEUS_METRICS = frozenset(
    {
        "recommendations_api_requests_total",
        "recommendations_api_errors_total",
        "recommendations_api_cold_start_total",
        "recommendations_api_latency_avg_ms",
    }
)

EXPECTED_DATADOG_METRICS = frozenset(
    {
        "recommendations_api.requests.total",
        "recommendations_api.errors.total",
        "recommendations_api.cold_start.total",
        "recommendations_api.latency.avg_ms",
        "recommendations_api.latency.p50_ms",
        "recommendations_api.latency.p95_ms",
    }
)


def known_user_id() -> str:
    """Return the primary user id used in live API tests."""
    return os.getenv("RECOMMENDATIONS_TEST_USER_ID", DEFAULT_KNOWN_USER_ID)


def cold_start_user_id() -> str:
    """Return the user id expected to trigger cold start."""
    return os.getenv("RECOMMENDATIONS_TEST_COLD_START_USER_ID", DEFAULT_COLD_START_USER_ID)


def normalize_api_base_url(base_url: str) -> str:
    """Ensure API Gateway invoke URLs include the REST stage."""
    normalized = base_url.rstrip("/")
    if normalized.endswith(f"/{API_STAGE}"):
        return normalized
    if "execute-api" in normalized:
        return f"{normalized}/{API_STAGE}"
    return normalized


def resolve_api_key(outputs: dict[str, str]) -> str:
    """Load the API Gateway key from Terraform outputs or SSM."""
    api_key = outputs.get("recommendations_api_key")
    if api_key:
        return api_key

    param_name = outputs.get("recommendations_api_key_ssm_parameter")
    if not param_name:
        pytest.skip(
            "Terraform outputs do not expose recommendations_api_key or "
            "recommendations_api_key_ssm_parameter."
        )

    region = os.getenv("AWS_REGION", "us-east-1")
    response = boto3.client("ssm", region_name=region).get_parameter(
        Name=param_name,
        WithDecryption=True,
    )
    return str(response["Parameter"]["Value"])


def load_api_gateway_config(outputs: dict[str, str]) -> tuple[str, str]:
    """Return ``(base_url, api_key)`` for the deployed recommendations API."""
    base_url = normalize_api_base_url(
        require_terraform_output(outputs, "recommendations_api_gateway_endpoint")
    )
    return base_url, resolve_api_key(outputs)


def build_api_client(base_url: str, api_key: str) -> httpx.Client:
    """Create an HTTP client configured for the recommendations API."""
    return httpx.Client(
        base_url=base_url,
        headers={"Accept": "application/json", "x-api-key": api_key},
        timeout=30.0,
    )


def wait_for_api_health(
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: float = 300,
    poll_interval_seconds: float = 10,
) -> None:
    """Poll ``/health`` until the recommendations API is ready or timeout."""
    import time

    deadline = time.monotonic() + timeout_seconds
    last_status: int | str = "unknown"
    while time.monotonic() < deadline:
        try:
            with build_api_client(base_url, api_key) as client:
                response = client.get("/health")
                last_status = response.status_code
                if response.status_code == 200:
                    return
        except httpx.HTTPError:
            last_status = "connection_error"
        time.sleep(poll_interval_seconds)

    pytest.fail(
        f"Recommendations API /health did not return 200 within {timeout_seconds}s "
        f"(last_status={last_status})."
    )


def parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Parse Prometheus text exposition into metric name → value."""
    metrics: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            value = float(line.rsplit(" ", 1)[1])
            if 'quantile="0.5"' in line:
                metrics["recommendations_api_latency_ms_p50"] = value
            elif 'quantile="0.95"' in line:
                metrics["recommendations_api_latency_ms_p95"] = value
            continue
        name, value = line.rsplit(" ", 1)
        metrics[name] = float(value)
    return metrics


def assert_readme_metrics(
    metrics_text: str,
    *,
    min_requests: int,
) -> None:
    """Assert Prometheus metrics match README observability requirements."""
    parsed = parse_prometheus_metrics(metrics_text)

    missing = EXPECTED_PROMETHEUS_METRICS - set(parsed)
    assert not missing, f"Missing Prometheus metrics: {sorted(missing)}"

    requests_total = parsed.get("recommendations_api_requests_total", 0.0)
    errors_total = parsed.get("recommendations_api_errors_total", 0.0)
    cold_start_total = parsed.get("recommendations_api_cold_start_total", 0.0)
    p50 = parsed.get("recommendations_api_latency_ms_p50", -1.0)
    p95 = parsed.get("recommendations_api_latency_ms_p95", -1.0)

    assert requests_total >= min_requests, (
        f"requests_total={requests_total}, expected>={min_requests}"
    )
    assert cold_start_total >= 1, f"cold_start_total={cold_start_total}"
    assert p50 >= 0, f"p50_ms={p50}"
    assert p95 >= 0, f"p95_ms={p95}"
    assert p95 >= p50, f"p50_ms={p50}, p95_ms={p95}"

    error_rate = (errors_total / requests_total) if requests_total else 0.0
    assert error_rate <= 0.5, f"error_rate={error_rate:.2%}"


def assert_datadog_metrics(payload: dict[str, Any]) -> None:
    """Assert Datadog series payload contains required metrics."""
    series = payload.get("series", [])
    assert series, "Datadog payload must include at least one series entry"

    metrics = {entry["metric"] for entry in series}
    missing = EXPECTED_DATADOG_METRICS - metrics
    assert not missing, f"Missing Datadog metrics: {sorted(missing)}"

    for entry in series:
        assert entry.get("type") in {1, 3}, f"unexpected type for {entry['metric']}"
        points = entry.get("points", [])
        assert points, f"no points for {entry['metric']}"
        assert "timestamp" in points[0] and "value" in points[0]
