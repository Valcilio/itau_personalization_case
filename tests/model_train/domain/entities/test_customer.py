"""Unit tests for model_train.domain.entities.customer."""

import pandas as pd
import pytest

from model_train.domain.entities.customer import Customer


def test_validate_accepts_valid_customer() -> None:
    Customer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=0.8,
        user_affinity_match=1,
    ).validate()


def test_validate_rejects_invalid_popularity_score() -> None:
    customer = Customer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=1.5,
        user_affinity_match=1,
    )
    with pytest.raises(ValueError, match="popularity_score"):
        customer.validate()


def test_from_row_builds_customer() -> None:
    row = pd.Series(
        {
            "user_id": "u_1",
            "product_id": "p_1",
            "interactions": 1,
            "price": 10.0,
            "avg_rating": 4.0,
            "popularity_score": 0.8,
            "user_affinity_match": 1,
        }
    )
    customer = Customer.from_row(row)
    assert customer.user_id == "u_1"


def test_validate_dataframe_returns_rows() -> None:
    features = pd.DataFrame(
        {
            "user_id": ["u_1"],
            "product_id": ["p_1"],
            "interactions": [1],
            "price": [10.0],
            "avg_rating": [4.0],
            "popularity_score": [0.8],
            "user_affinity_match": [1],
        }
    )
    assert len(Customer.validate_dataframe(features)) == 1


def test_validate_dataframe_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="Missing required feature columns"):
        Customer.validate_dataframe(pd.DataFrame({"user_id": ["u_1"]}))
