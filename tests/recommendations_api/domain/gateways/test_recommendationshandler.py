"""Unit tests for recommendations_api.domain.gateways.recommendationshandler."""

import pytest

from recommendations_api.domain.entities.user import User
from recommendations_api.domain.gateways.recommendationshandler import RecommendationsHandler
from tests.helpers.recommendations_fixtures import build_recommendations_handler


def test_get_recommendation_returns_compact_payload() -> None:
    payload = build_recommendations_handler().get_recommendation("u_0231")
    assert payload["user_id"] == "u_0231"
    assert payload["cold_start_flag"] is False
    assert payload["recommendations"][0]["product_id"] == "p_001"


def test_get_recommendation_rejects_invalid_user() -> None:
    with pytest.raises(ValueError):
        build_recommendations_handler().get_recommendation("bad_user")


def test_get_filtered_recommendations_applies_filters() -> None:
    payload = build_recommendations_handler().get_filtered_recommendations(
        {
            "user_id": "u_0231",
            "limit": 2,
            "exclude_product_ids": ["p_002"],
            "min_recommendation_score": 0.5,
            "context": {"campaign": "black_friday"},
        }
    )
    assert payload["count"] == 2
    assert payload["context"]["campaign"] == "black_friday"
    assert all(item["product_id"] != "p_002" for item in payload["recommendations"])


def test_get_filtered_recommendations_uses_cold_start() -> None:
    handler = build_recommendations_handler()
    payload = handler.get_filtered_recommendations({"user_id": "u_9999", "limit": 2})
    assert payload["cold_start_flag"] is True
    assert payload["count"] == 2
