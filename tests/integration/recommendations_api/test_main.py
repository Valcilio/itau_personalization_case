"""Live AWS integration test for recommendations_api."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from tests.helpers.aws_integration import (
    dynamodb_table_has_items,
    recommendations_api_env,
    temporary_env,
)


@pytest.fixture
def live_app(terraform_outputs):
    """Reload the FastAPI app with real AWS connectors (no handler mocks)."""
    env = recommendations_api_env(terraform_outputs)
    table_name = env["PREDICTIONS_DYNAMODB_TABLE"]
    if not dynamodb_table_has_items(table_name):
        pytest.skip(
            "Predictions table is empty; run model_predict integration test first."
        )

    with temporary_env(env):
        import recommendations_api.main as main_module

        importlib.reload(main_module)
        main_module._HandlerHolder.instance = None  # noqa: SLF001 - reset singleton
        main_module.metrics = main_module.create_metrics_collector()
        yield main_module.app, main_module


def test_recommendations_api_reads_predictions_from_dynamodb(live_app) -> None:
    """Exercise HTTP endpoints against live DynamoDB and S3-backed cold start."""
    app, main_module = live_app
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    recommendation = client.get("/recommendations/u_0231")
    assert recommendation.status_code == 200
    body = recommendation.json()
    assert body["user_id"] == "u_0231"
    assert body["count"] > 0
    assert "score" in body["recommendations"][0]

    cold_start = client.get("/recommendations/u_9999")
    assert cold_start.status_code == 200
    assert cold_start.json()["cold_start_flag"] is True

    filtered = client.post(
        "/recommendations_filtered",
        json={
            "user_id": "u_0231",
            "limit": 5,
            "exclude_product_ids": [],
            "context": {"device": "integration-test"},
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] <= 5

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "recommendations_api_requests_total" in metrics.text

    # Ensure metrics persistence path was exercised (DynamoDB store).
    assert main_module.metrics.store.__class__.__name__ == "DynamoDBMetricsStore"
