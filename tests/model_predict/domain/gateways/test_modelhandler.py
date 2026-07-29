"""Unit tests for model_predict.domain.gateways.modelhandler."""

import pickle
from pathlib import Path

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_predict.domain.entities.costumer import Costumer
from model_predict.domain.gateways.modelhandler import ModelHandler


def _write_artifact(tmp_path: Path) -> Path:
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
    feature_values = feature_matrix.to_numpy()
    scaler = StandardScaler().fit(feature_values)
    model = LogisticRegression(max_iter=1000).fit(scaler.transform(feature_values), labels)
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
    return tmp_path


def test_load_artifact_reads_model(tmp_path: Path) -> None:
    artifact_dir = _write_artifact(tmp_path)
    loaded = ModelHandler().load_artifact(artifact_dir)
    assert loaded.feature_cols == list(Costumer.FEATURE_COLUMNS)


def test_load_artifact_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ModelHandler().load_artifact(tmp_path)


def test_run_predictions_returns_handler_result(
    tmp_path: Path,
    sample_events,
    sample_products,
) -> None:
    artifact_dir = _write_artifact(tmp_path)
    result = ModelHandler().run_predictions(sample_events, sample_products, artifact_dir)
    assert result.validated_costumers == 4
    assert "purchase_proba" in result.predictions.columns
