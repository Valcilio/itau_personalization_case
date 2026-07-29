"""Unit tests for model_predict.domain.usecases.featureengineer."""

import pandas as pd
from sklearn.preprocessing import StandardScaler

from model_predict.domain.entities.costumer import Costumer
from model_predict.domain.usecases.featureengineer import FeatureEngineer


def test_build_returns_scaled_features(sample_events, sample_products) -> None:
    features_raw = pd.DataFrame(
        {
            "interactions": [1, 0, 1, 0],
            "price": [10.0, 20.0, 10.0, 20.0],
            "avg_rating": [4.0, 3.5, 4.0, 3.5],
            "popularity_score": [0.8, 0.2, 0.8, 0.2],
            "user_affinity_match": [1, 0, 0, 1],
        }
    )
    scaler = StandardScaler().fit(features_raw.to_numpy())
    engineer = FeatureEngineer(
        events=sample_events,
        products=sample_products,
        scaler=scaler,
    )

    features, scaled_features = engineer.build()

    assert len(features) == 4
    assert list(scaled_features.columns) == list(Costumer.FEATURE_COLUMNS)
    assert "user_id" in features.columns
    assert "product_id" in features.columns
