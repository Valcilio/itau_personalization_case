from pathlib import Path

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_predict.domain.entities.costumer import Costumer
from model_predict.domain.gateways.modelhandler import ModelHandler
from model_predict.domain.usecases.featureengineer import FeatureEngineer
from model_predict.domain.usecases.modelrunner import ModelRunner


def _sample_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    events = pd.DataFrame(
        {
            "user_id": ["u_1", "u_1", "u_2"],
            "product_id": ["p_1", "p_1", "p_2"],
            "event_type": ["view", "purchase", "click"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": ["p_1", "p_2"],
            "category": ["livros", "esporte"],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
        }
    )
    return events, products


def test_costumer_validates_required_features() -> None:
    costumer = Costumer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=0.8,
        user_affinity_match=1,
    )
    costumer.validate()


def test_costumer_rejects_invalid_popularity_score() -> None:
    costumer = Costumer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=1.5,
        user_affinity_match=1,
    )
    with pytest.raises(ValueError, match="popularity_score"):
        costumer.validate()


def test_feature_engineer_builds_scaled_features() -> None:
    events, products = _sample_frames()
    features_raw = pd.DataFrame(
        {
            "interactions": [1, 0, 1, 0],
            "price": [10.0, 20.0, 10.0, 20.0],
            "avg_rating": [4.0, 3.5, 4.0, 3.5],
            "popularity_score": [0.8, 0.2, 0.8, 0.2],
            "user_affinity_match": [1, 0, 0, 1],
        }
    )
    scaler = StandardScaler().fit(features_raw)

    engineer = FeatureEngineer(events=events, products=products, scaler=scaler)
    features, scaled_features = engineer.build()

    assert len(features) == 4
    assert list(scaled_features.columns) == list(Costumer.FEATURE_COLUMNS)
    assert "user_id" in features.columns
    assert "product_id" in features.columns


def test_model_runner_adds_purchase_proba() -> None:
    events, products = _sample_frames()
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

    engineer = FeatureEngineer(events=events, products=products, scaler=scaler)
    features, scaled_features = engineer.build()
    predictions = ModelRunner(model=model).run(features, scaled_features)

    assert "purchase_proba" in predictions.columns
    assert len(predictions) == len(features)
    assert predictions["purchase_proba"].between(0, 1).all()


def test_model_handler_loads_artifact_and_predicts(tmp_path: Path) -> None:
    events, products = _sample_frames()
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

    import pickle

    artifact_path = tmp_path / "model.pkl"
    with artifact_path.open("wb") as artifact_file:
        pickle.dump(
            {
                "model": model,
                "scaler": scaler,
                "feature_cols": list(Costumer.FEATURE_COLUMNS),
            },
            artifact_file,
        )

    handler = ModelHandler()
    result = handler.run_predictions(events, products, tmp_path)

    assert result.validated_costumers == 4
    assert len(result.predictions) == 4
    assert "purchase_proba" in result.predictions.columns


def test_format_predictions_for_output() -> None:
    from model_predict.main import format_predictions_for_output

    predictions = pd.DataFrame(
        {
            "user_id": ["u_1", "u_2"],
            "product_id": ["p_1", "p_2"],
            "interactions": [2, 0],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
            "user_affinity_match": [1, 0],
            "purchase_proba": [0.9, 0.1],
        }
    )

    formatted = format_predictions_for_output(predictions)

    assert list(formatted.columns) == [
        "user_id",
        "product_id",
        "is_cold_start",
        "interactions",
        "price",
        "avg_rating",
        "popularity_score",
        "user_affinity_match",
        "recommendation_score",
    ]
    assert "purchase_proba" not in formatted.columns
    assert (formatted["is_cold_start"] == False).all()  # noqa: E712
    assert formatted.iloc[0]["user_id"] == "u_2"
