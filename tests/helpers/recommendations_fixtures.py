"""Reusable mocks and sample data for recommendations API tests."""

from __future__ import annotations

import pandas as pd

from recommendations_api.domain.gateways.recommendationshandler import (
    RecommendationsHandler,
)
from recommendations_api.domain.usecases.recommendationsfilter import RecommendationsFilter
from recommendations_api.domain.usecases.recommendationsretriever import (
    RecommendationsRetriever,
)
from recommendations_api.domain.usecases.recommendationsstructurer import (
    RecommendationsStructurer,
)


class FakeAwsConnector:
    """In-memory AWS gateway mock for recommendations tests."""

    def __init__(self, predictions: pd.DataFrame, products: pd.DataFrame) -> None:
        self.predictions = predictions
        self.products = products

    def get_user_predictions(self, user_id: str) -> pd.DataFrame:
        frame = self.predictions[self.predictions["user_id"] == user_id].copy()
        return frame.reset_index(drop=True)

    def get_cold_start_predictions(self, limit: int) -> pd.DataFrame:
        cold = self.products.sort_values("popularity_score", ascending=False).head(limit).copy()
        cold["recommendation_score"] = cold["popularity_score"].astype(float)
        cold["user_id"] = "cold_start"
        cold["is_cold_start"] = True
        cold["interactions"] = 0
        cold["user_affinity_match"] = 0
        return cold[
            [
                "user_id",
                "product_id",
                "is_cold_start",
                "interactions",
                "price",
                "avg_rating",
                "popularity_score",
                "user_affinity_match",
                "recommendation_score",
                "category",
            ]
        ].reset_index(drop=True)

    def get_products_catalog(self) -> pd.DataFrame:
        return self.products.copy()


def sample_recommendation_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    products = pd.DataFrame(
        {
            "product_id": ["p_001", "p_002", "p_003"],
            "category": ["livros", "esporte", "moda"],
            "price": [10.0, 50.0, 30.0],
            "avg_rating": [4.5, 3.0, 4.0],
            "popularity_score": [0.9, 0.4, 0.7],
        }
    )
    predictions = pd.DataFrame(
        {
            "user_id": ["u_0231", "u_0231", "u_0231"],
            "product_id": ["p_001", "p_002", "p_003"],
            "is_cold_start": [False, False, False],
            "interactions": [2, 0, 1],
            "price": [10.0, 50.0, 30.0],
            "avg_rating": [4.5, 3.0, 4.0],
            "popularity_score": [0.9, 0.4, 0.7],
            "user_affinity_match": [1, 0, 1],
            "recommendation_score": [0.95, 0.20, 0.80],
            "category": ["livros", "esporte", "moda"],
        }
    )
    return predictions, products


def build_recommendations_handler() -> RecommendationsHandler:
    predictions, products = sample_recommendation_data()
    aws = FakeAwsConnector(predictions, products)
    return RecommendationsHandler(
        aws_connector=aws,
        retriever=RecommendationsRetriever(aws),
        filter_use_case=RecommendationsFilter(),
        structurer=RecommendationsStructurer(),
    )
