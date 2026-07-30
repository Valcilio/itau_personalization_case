"""Unit tests for recommendations_api.main."""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from recommendations_api.domain.utils.apilogger import ApiLogger
from recommendations_api.domain.utils.metrics import create_metrics_collector
from recommendations_api.main import (
    app,
    get_handler,
    get_metrics,
    health,
    set_handler,
    set_metrics_collector,
)
from tests.helpers.recommendations_fixtures import build_recommendations_handler


def _reset_app() -> None:
    set_handler(build_recommendations_handler())
    set_metrics_collector(create_metrics_collector())


def test_health_returns_ok() -> None:
    assert health() == {"status": "ok"}


def test_get_handler_creates_singleton() -> None:
    _reset_app()
    assert get_handler() is get_handler()


def test_set_handler_overrides_instance() -> None:
    handler = build_recommendations_handler()
    set_handler(handler)
    assert get_handler() is handler


def test_get_recommendation_endpoint() -> None:
    _reset_app()
    response = TestClient(app).get("/recommendation/u_0231")
    assert response.status_code == 200
    assert response.json()["user_id"] == "u_0231"


def test_get_recommendation_invalid_user_returns_400() -> None:
    _reset_app()
    response = TestClient(app).get("/recommendation/bad_user")
    assert response.status_code == 400


def test_cold_start_endpoint() -> None:
    _reset_app()
    response = TestClient(app).get("/recommendations/u_9999")
    body = response.json()
    assert body["cold_start_flag"] is True
    assert body["recommendations"][0]["score"] == 0.9


def test_filtered_endpoint_and_metrics() -> None:
    _reset_app()
    client = TestClient(app)
    response = client.post(
        "/recommendation_filtered",
        json={
            "user_id": "u_0231",
            "limit": 2,
            "exclude_product_ids": ["p_002"],
            "min_recommendation_score": 0.5,
        },
    )
    assert response.status_code == 200
    assert response.json()["count"] == 2

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "recommendations_api_requests_total" in metrics_response.text


def test_get_metrics_returns_prometheus_text(capsys) -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure()

    _reset_app()
    client = TestClient(app)
    client.get("/recommendation/u_0231")
    response = client.get("/metrics")
    assert "text/plain" in response.headers.get("content-type", "")
    assert get_metrics.__name__ == "get_metrics"
    assert "api_metrics_snapshot" in capsys.readouterr().out


def test_get_metrics_datadog_format() -> None:
    _reset_app()
    client = TestClient(app)
    client.get("/recommendation/u_0231")

    response = client.get("/metrics?format=datadog")
    assert response.status_code == 200
    body = response.json()
    assert "series" in body
    metrics = {item["metric"]: item for item in body["series"]}
    assert metrics["recommendations_api.requests.total"]["type"] == 1
    assert metrics["recommendations_api.latency.p95_ms"]["type"] == 3


def test_get_metrics_both_format() -> None:
    _reset_app()
    client = TestClient(app)
    client.get("/recommendation/u_0231")

    response = client.get("/metrics?format=both")
    assert response.status_code == 200
    body = response.json()
    assert "prometheus" in body
    assert "datadog" in body
    assert "recommendations_api_requests_total" in body["prometheus"]


def test_get_metrics_invalid_format_returns_400() -> None:
    _reset_app()
    response = TestClient(app).get("/metrics?format=statsd")
    assert response.status_code == 400
