"""Unit tests for recommendations_api.domain.usecases.recommendationsfilter."""

from recommendations_api.domain.entities.user import User
from recommendations_api.domain.usecases.recommendationsfilter import RecommendationsFilter
from tests.helpers.recommendations_fixtures import build_recommendations_handler


def test_apply_excludes_products_and_categories() -> None:
    handler = build_recommendations_handler()
    filters = User.validate_filtered_request(
        {
            "user_id": "u_0231",
            "exclude_product_ids": ["p_001"],
            "categories": ["moda", "esporte"],
            "limit": 10,
        }
    )
    predictions = handler.aws_connector.get_user_predictions("u_0231")
    filtered = RecommendationsFilter().apply(predictions, filters)
    assert list(filtered["product_id"]) == ["p_003", "p_002"]


def test_apply_filters_by_single_category() -> None:
    handler = build_recommendations_handler()
    filters = User.validate_filtered_request(
        {"user_id": "u_0231", "category": "moda", "limit": 10}
    )
    predictions = handler.aws_connector.get_user_predictions("u_0231")
    filtered = RecommendationsFilter().apply(predictions, filters)
    assert not filtered.empty
    assert (filtered["category"] == "moda").all()


def test_apply_respects_min_recommendation_score() -> None:
    handler = build_recommendations_handler()
    filters = User.validate_filtered_request(
        {"user_id": "u_0231", "min_recommendation_score": 0.5}
    )
    predictions = handler.aws_connector.get_user_predictions("u_0231")
    filtered = RecommendationsFilter().apply(predictions, filters)
    assert all(filtered["recommendation_score"] >= 0.5)
