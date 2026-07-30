"""Unit tests for model prediction snapshot validation."""

import pandas as pd
import pytest

from model_drift_monitor.domain.entities.model import ModelPredictionSnapshot


def test_validate_dataframe_accepts_valid_predictions() -> None:
    predictions = pd.DataFrame(
        {
            "user_id": ["u_0001"],
            "product_id": ["p_0001"],
            "recommendation_score": [0.8],
            "interactions": [2],
            "price": [10.0],
            "avg_rating": [4.5],
            "popularity_score": [0.7],
            "user_affinity_match": [1],
        }
    )
    validated = ModelPredictionSnapshot.validate_dataframe(predictions)
    assert len(validated) == 1


def test_validate_dataframe_rejects_invalid_score() -> None:
    predictions = pd.DataFrame(
        {
            "user_id": ["u_0001"],
            "product_id": ["p_0001"],
            "recommendation_score": [1.5],
            "interactions": [2],
            "price": [10.0],
            "avg_rating": [4.5],
            "popularity_score": [0.7],
            "user_affinity_match": [1],
        }
    )
    with pytest.raises(ValueError, match="recommendation_score"):
        ModelPredictionSnapshot.validate_dataframe(predictions)
