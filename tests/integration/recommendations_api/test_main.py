"""Live AWS integration test for recommendations_api."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from recommendations_api.domain.gateways.recommendationshandler import (
    RecommendationsHandler,
)
from recommendations_api.domain.utils.metrics import create_metrics_collector
from recommendations_api.main import app, set_handler, set_metrics_collector
from tests.helpers.aws_integration import (
    dynamodb_table_has_items,
    recommendations_api_env,
    temporary_env,
)

pytestmark = [pytest.mark.integration, pytest.mark.order(3)]


@pytest.fixture
def live_client(terraform_outputs):
    """Configure the API with real AWS connectors (no mocks)."""
    env = recommendations_api_env(terraform_outputs)
    table_name = env["PREDICTIONS_DYNAMODB_TABLE"]
    if not dynamodb_table_has_items(table_name):
        pytest.skip(
            "Predictions table is empty; run model_predict integration test first."
        )

    with temporary_env(env):
        set_handler(RecommendationsHandler())
        collector = create_metrics_collector()
        set_metrics_collector(collector)
        yield TestClient(app), collector


def test_recommendations_api_reads_predictions_from_dynamodb(live_client) -> None:
    """Exercise HTTP endpoints against live DynamoDB and S3-backed cold start."""
    client, collector = live_client

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
            "category": "moda",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] <= 5

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "recommendations_api_requests_total" in metrics.text
    assert collector.store.__class__.__name__ == "InMemoryMetricsStore"
