"""Unit tests for model_predict.domain.usecases.modelrunner."""

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_predict.domain.usecases.featureengineer import FeatureEngineer
from model_predict.domain.usecases.modelrunner import ModelRunner


def test_run_adds_purchase_proba(sample_events, sample_products) -> None:
    feature_matrix = pd.DataFrame(
        {
            "interactions": [2.0, 0.0],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
            "user_affinity_match": [1.0, 0.0],
        }
    )
    labels = pd.Series([1, 0])
    scaler = StandardScaler().fit(feature_matrix)
    model = LogisticRegression(max_iter=1000).fit(scaler.transform(feature_matrix), labels)

    engineer = FeatureEngineer(events=sample_events, products=sample_products, scaler=scaler)
    features, scaled_features = engineer.build()
    predictions = ModelRunner(model=model).run(features, scaled_features)

    assert "purchase_proba" in predictions.columns
    assert len(predictions) == len(features)
    assert predictions["purchase_proba"].between(0, 1).all()
