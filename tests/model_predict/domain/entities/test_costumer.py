"""Unit tests for model_predict.domain.entities.costumer."""

import pandas as pd
import pytest

from model_predict.domain.entities.costumer import Costumer


def _valid_costumer() -> Costumer:
    return Costumer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=0.8,
        user_affinity_match=1,
    )


def test_validate_accepts_valid_costumer() -> None:
    _valid_costumer().validate()


def test_validate_rejects_empty_user_id() -> None:
    costumer = _valid_costumer()
    invalid = Costumer(
        user_id="",
        product_id=costumer.product_id,
        interactions=costumer.interactions,
        price=costumer.price,
        avg_rating=costumer.avg_rating,
        popularity_score=costumer.popularity_score,
        user_affinity_match=costumer.user_affinity_match,
    )
    with pytest.raises(ValueError, match="user_id"):
        invalid.validate()


def test_validate_rejects_negative_interactions() -> None:
    costumer = Costumer(
        user_id="u_1",
        product_id="p_1",
        interactions=-1,
        price=10.0,
        avg_rating=4.0,
        popularity_score=0.8,
        user_affinity_match=1,
    )
    with pytest.raises(ValueError, match="interactions"):
        costumer.validate()


def test_validate_rejects_invalid_popularity_score() -> None:
    costumer = Costumer(
        user_id="u_1",
        product_id="p_1",
        interactions=1,
        price=10.0,
        avg_rating=4.0,
        popularity_score=1.5,
        user_affinity_match=1,
    )
    with pytest.raises(ValueError, match="popularity_score"):
        costumer.validate()


def test_from_row_builds_costumer() -> None:
    row = pd.Series(
        {
            "user_id": "u_1",
            "product_id": "p_1",
            "interactions": 2,
            "price": 10.0,
            "avg_rating": 4.0,
            "popularity_score": 0.8,
            "user_affinity_match": 1,
        }
    )
    costumer = Costumer.from_row(row)
    assert costumer.user_id == "u_1"
    assert costumer.product_id == "p_1"


def test_validate_dataframe_returns_validated_rows() -> None:
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
    costumers = Costumer.validate_dataframe(features)
    assert len(costumers) == 1


def test_validate_dataframe_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="Missing required feature columns"):
        Costumer.validate_dataframe(pd.DataFrame({"user_id": ["u_1"]}))
