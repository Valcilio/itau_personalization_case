"""Unit tests for recommendations_api.domain.usecases.recommendationsretriever."""

import pandas as pd

from recommendations_api.domain.usecases.recommendationsretriever import RecommendationsRetriever
from tests.helpers.recommendations_fixtures import FakeAwsConnector, sample_recommendation_data


def test_retrieve_returns_top_scores() -> None:
    predictions, products = sample_recommendation_data()
    retriever = RecommendationsRetriever(FakeAwsConnector(predictions, products))
    frame, cold_start = retriever.retrieve("u_0231", limit=2)
    assert cold_start is False
    assert list(frame["product_id"]) == ["p_001", "p_003"]


def test_retrieve_uses_cold_start_for_unknown_user() -> None:
    predictions, products = sample_recommendation_data()
    retriever = RecommendationsRetriever(FakeAwsConnector(predictions, products))
    frame, cold_start = retriever.retrieve("u_9999", limit=2)
    assert cold_start is True
    assert frame.iloc[0]["recommendation_score"] == frame.iloc[0]["popularity_score"]


def test_retrieve_uses_stored_is_cold_start_flag() -> None:
    predictions, products = sample_recommendation_data()
    stored = predictions[predictions["user_id"] == "u_0231"].copy()
    retriever = RecommendationsRetriever(FakeAwsConnector(stored, products))
    _, cold_start = retriever.retrieve("u_0231", limit=2)
    assert cold_start is False


def test_retrieve_filters_other_users_rows() -> None:
    mixed_predictions = pd.DataFrame(
        {
            "user_id": ["u_0231", "u_0231", "u_0078"],
            "product_id": ["p_001", "p_002", "p_003"],
            "recommendation_score": [0.80, 0.70, 0.99],
            "is_cold_start": [False, False, False],
            "interactions": [1, 0, 5],
            "price": [10.0, 20.0, 30.0],
            "avg_rating": [4.0, 4.0, 4.0],
            "popularity_score": [0.5, 0.5, 0.9],
            "user_affinity_match": [1, 0, 1],
            "category": ["livros", "moda", "esporte"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": ["p_001", "p_002", "p_003"],
            "category": ["livros", "moda", "esporte"],
            "price": [10.0, 20.0, 30.0],
            "avg_rating": [4.0, 4.0, 4.0],
            "popularity_score": [0.5, 0.5, 0.9],
        }
    )

    class MixedGateway:
        def get_user_predictions(self, user_id: str) -> pd.DataFrame:
            return mixed_predictions.copy()

        def get_cold_start_predictions(self, limit: int) -> pd.DataFrame:
            return FakeAwsConnector(mixed_predictions, products).get_cold_start_predictions(limit)

    frame, cold_start = RecommendationsRetriever(MixedGateway()).retrieve("u_0231", limit=10)
    assert cold_start is False
    assert list(frame["product_id"]) == ["p_001", "p_002"]
