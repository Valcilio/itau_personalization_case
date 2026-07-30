"""Live API Gateway smoke tests (ported from notebooks/testing_endpoint.ipynb)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.order(4)]


def test_api_base_url_includes_stage(api_base_url, api_stage) -> None:
    assert api_base_url.endswith(f"/{api_stage}")


def test_health_is_public(api_client) -> None:
    response = api_client.get("/health", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommendations_for_known_user(
    api_client,
    known_user,
    production_predictions_ready,
) -> None:
    response = api_client.get(f"/recommendations/{known_user}")
    body = response.json()

    assert response.status_code == 200
    assert body.get("count", 0) > 0
    assert body.get("recommendations")
    assert all("score" in item for item in body["recommendations"])
    assert body.get("cold_start_flag") is False


def test_recommendation_singular_alias(
    api_client,
    known_user,
    production_predictions_ready,
) -> None:
    response = api_client.get(f"/recommendation/{known_user}")
    assert response.status_code == 200
    assert response.json().get("user_id") == known_user


def test_cold_start_user(api_client, cold_start_user) -> None:
    response = api_client.get(f"/recommendations/{cold_start_user}")
    assert response.status_code == 200
    assert response.json().get("cold_start_flag") is True


def test_filtered_recommendations(
    api_client,
    known_user,
    production_predictions_ready,
) -> None:
    baseline = api_client.get(f"/recommendations/{known_user}").json()
    excluded_product_id = baseline["recommendations"][0]["product_id"]

    response = api_client.post(
        "/recommendations_filtered",
        json={
            "user_id": known_user,
            "limit": 5,
            "exclude_product_ids": [excluded_product_id],
            "category": "esporte",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body.get("count", 0) <= 5
    assert all(
        {"product_id", "recommendation_score", "category"} <= set(item)
        for item in body.get("recommendations", [])
    )
    assert body.get("category") == "esporte"
    assert all(
        item.get("category") == "esporte" for item in body.get("recommendations", [])
    )


def test_recommendation_filtered_alias(api_client, known_user) -> None:
    response = api_client.post(
        "/recommendation_filtered",
        json={"user_id": known_user, "limit": 3},
    )
    assert response.status_code == 200


def test_invalid_user_returns_400(api_client) -> None:
    response = api_client.get("/recommendations/invalid_user")
    assert response.status_code == 400


def test_protected_route_requires_api_key(api_base_url, known_user) -> None:
    with httpx.Client(base_url=api_base_url, timeout=30.0) as client:
        response = client.get(f"/recommendations/{known_user}")
    assert response.status_code in {401, 403}
