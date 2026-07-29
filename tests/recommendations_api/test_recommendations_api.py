from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from recommendations_api.domain.entities.user import User
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
from recommendations_api.main import app, set_handler


class FakeAwsConnector:
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


def _sample_data() -> tuple[pd.DataFrame, pd.DataFrame]:
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


def _build_handler() -> RecommendationsHandler:
    predictions, products = _sample_data()
    aws = FakeAwsConnector(predictions, products)
    return RecommendationsHandler(
        aws_connector=aws,
        retriever=RecommendationsRetriever(aws),
        filter_use_case=RecommendationsFilter(),
        structurer=RecommendationsStructurer(),
    )


def test_user_validates_user_id() -> None:
    user = User.validate_user_id("u_0231")
    assert user.user_id == "u_0231"
    with pytest.raises(ValueError):
        User.validate_user_id("invalid")


def test_user_validates_filtered_request() -> None:
    filters = User.validate_filtered_request(
        {
            "user_id": "u_0231",
            "limit": 5,
            "exclude_product_ids": ["p_002"],
            "categories": ["livros"],
            "min_price": 5,
            "max_price": 40,
            "context": {"device": "mobile"},
        }
    )
    assert filters.limit == 5
    assert filters.exclude_product_ids == ["p_002"]
    with pytest.raises(ValueError, match="min_price"):
        User.validate_filtered_request(
            {"user_id": "u_0231", "min_price": 50, "max_price": 10}
        )


def test_retriever_returns_top_scores() -> None:
    handler = _build_handler()
    frame, cold_start = handler.retriever.retrieve("u_0231", limit=2)
    assert cold_start is False
    assert list(frame["product_id"]) == ["p_001", "p_003"]


def test_retriever_cold_start_uses_popularity_score() -> None:
    handler = _build_handler()
    frame, cold_start = handler.retriever.retrieve("u_9999", limit=2)
    assert cold_start is True
    assert len(frame) == 2
    assert frame.iloc[0]["product_id"] == "p_001"
    assert frame.iloc[0]["recommendation_score"] == frame.iloc[0]["popularity_score"]


def test_filter_applies_exclude_and_category() -> None:
    handler = _build_handler()
    filters = User.validate_filtered_request(
        {
            "user_id": "u_0231",
            "exclude_product_ids": ["p_001"],
            "categories": ["moda", "esporte"],
            "limit": 10,
        }
    )
    predictions = handler.aws_connector.get_user_predictions("u_0231")
    filtered = handler.filter_use_case.apply(predictions, filters)
    assert list(filtered["product_id"]) == ["p_003", "p_002"]


def test_get_recommendation_endpoint() -> None:
    set_handler(_build_handler())
    client = TestClient(app)
    response = client.get("/recommendation/u_0231")
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u_0231"
    assert body["cold_start_flag"] is False
    assert body["recommendations"][0]["product_id"] == "p_001"
    assert "score" in body["recommendations"][0]


def test_get_recommendation_invalid_user() -> None:
    set_handler(_build_handler())
    client = TestClient(app)
    response = client.get("/recommendation/bad_user")
    assert response.status_code == 400


def test_cold_start_endpoint() -> None:
    set_handler(_build_handler())
    client = TestClient(app)
    response = client.get("/recommendations/u_9999")
    assert response.status_code == 200
    body = response.json()
    assert body["cold_start_flag"] is True
    assert body["count"] > 0
    assert body["recommendations"][0]["score"] == 0.9


def test_filtered_endpoint_integration() -> None:
    set_handler(_build_handler())
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    response = client.post(
        "/recommendation_filtered",
        json={
            "user_id": "u_0231",
            "limit": 2,
            "exclude_product_ids": ["p_002"],
            "min_recommendation_score": 0.5,
            "context": {"device": "mobile", "campaign": "black_friday"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["cold_start_flag"] is False
    assert body["context"]["campaign"] == "black_friday"
    assert all("recommendation_score" in item for item in body["recommendations"])
    assert all(item["product_id"] != "p_002" for item in body["recommendations"])

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "recommendations_api_requests_total" in metrics.text
