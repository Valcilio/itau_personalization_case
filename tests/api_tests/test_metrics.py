"""Live API Gateway metrics validation tests."""

from __future__ import annotations

import pytest

from tests.helpers.api_gateway import assert_datadog_metrics, assert_readme_metrics

pytestmark = [pytest.mark.integration, pytest.mark.order(5)]


def test_prometheus_metrics_endpoint(api_client) -> None:
    """Metrics must satisfy README observability requirements after smoke tests."""
    response = api_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in (response.headers.get("content-type") or "")

    assert_readme_metrics(response.text, min_requests=6)


def test_datadog_metrics_format(api_client) -> None:
    response = api_client.get("/metrics?format=datadog")
    assert response.status_code == 200
    assert "application/json" in (response.headers.get("content-type") or "")

    assert_datadog_metrics(response.json())
