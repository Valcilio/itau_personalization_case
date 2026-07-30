"""Unit tests for recommendations_api.domain.usecases.recommendationsstructurer."""

import pandas as pd

from recommendations_api.domain.usecases.recommendationsstructurer import RecommendationsStructurer


def test_structure_recommendation_returns_compact_payload() -> None:
    frame = pd.DataFrame(
        {
            "user_id": ["u_0231"],
            "product_id": ["p_001"],
            "recommendation_score": [0.95],
            "popularity_score": [0.9],
        }
    )
    payload = RecommendationsStructurer().structure_recommendation("u_0231", frame, False)
    assert payload["cold_start_flag"] is False
    assert payload["recommendations"][0]["score"] == 0.95


def test_structure_recommendation_uses_popularity_on_cold_start() -> None:
    frame = pd.DataFrame(
        {
            "product_id": ["p_001"],
            "recommendation_score": [0.1],
            "popularity_score": [0.9],
        }
    )
    payload = RecommendationsStructurer().structure_recommendation("u_9999", frame, True)
    assert payload["recommendations"][0]["score"] == 0.9


def test_structure_filtered_returns_detailed_payload() -> None:
    frame = pd.DataFrame(
        {
            "user_id": ["u_0231"],
            "product_id": ["p_001"],
            "is_cold_start": [False],
            "interactions": [1],
            "price": [10.0],
            "avg_rating": [4.5],
            "popularity_score": [0.9],
            "user_affinity_match": [1],
            "recommendation_score": [0.95],
            "category": ["livros"],
        }
    )
    payload = RecommendationsStructurer().structure_filtered(
        "u_0231",
        frame,
        False,
        category="livros",
    )
    assert payload["category"] == "livros"
    assert payload["recommendations"][0]["recommendation_score"] == 0.95
