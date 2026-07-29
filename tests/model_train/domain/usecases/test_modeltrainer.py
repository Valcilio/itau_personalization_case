"""Unit tests for model_train.domain.usecases.modeltrainer."""

import pandas as pd

from model_train.domain.usecases.modeltrainer import ModelTrainer


def test_train_returns_metrics_and_artifacts() -> None:
    features = pd.DataFrame(
        {
            "user_id": ["u_1", "u_1", "u_2", "u_2", "u_3", "u_3"],
            "product_id": ["p_1", "p_2", "p_1", "p_2", "p_1", "p_2"],
            "interactions": [2, 0, 1, 0, 3, 1],
            "price": [10.0, 20.0, 10.0, 20.0, 10.0, 20.0],
            "avg_rating": [4.0, 3.5, 4.0, 3.5, 4.0, 3.5],
            "popularity_score": [0.8, 0.2, 0.8, 0.2, 0.8, 0.2],
            "user_affinity_match": [1, 0, 0, 1, 1, 0],
        }
    )
    labels = pd.Series([1, 0, 0, 1, 1, 0])
    result = ModelTrainer(test_size=0.34, random_state=42).train(features, labels)
    assert result.validated_customers == 6
    assert "accuracy" in result.metrics
    assert "roc_auc" in result.metrics
