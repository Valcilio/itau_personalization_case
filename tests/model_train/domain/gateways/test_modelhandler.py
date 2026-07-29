"""Unit tests for model_train.domain.gateways.modelhandler."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_train.domain.entities.customer import Customer
from model_train.domain.gateways.modelhandler import ModelHandler
from model_train.domain.usecases.modeltrainer import ModelTrainer, TrainingResult


def test_build_training_dataset_creates_binary_labels(sample_events, sample_products) -> None:
    handler = ModelHandler()
    features, labels = handler.build_training_dataset(sample_events, sample_products)
    assert list(handler.FEATURE_COLUMNS) == list(Customer.FEATURE_COLUMNS)
    assert len(features) == 2
    assert labels.tolist() == [1, 0]


def test_create_artifact_contains_model_and_scaler() -> None:
    handler = ModelHandler()
    model = LogisticRegression(max_iter=1000)
    scaler = StandardScaler()
    artifact = handler.create_artifact(model, scaler)
    assert set(artifact.keys()) == {"model", "scaler", "feature_cols"}


def test_save_artifact_writes_pickle(tmp_path: Path) -> None:
    handler = ModelHandler()
    artifact = handler.create_artifact(LogisticRegression(), StandardScaler())
    path = handler.save_artifact(artifact, tmp_path)
    assert path.exists()


def test_save_model_card_writes_json(tmp_path: Path) -> None:
    handler = ModelHandler()
    path = handler.save_model_card(tmp_path, {"accuracy": 0.9, "roc_auc": 0.8}, "v1")
    assert path.exists()


def test_train_and_persist_with_mocked_trainer(tmp_path: Path, sample_events, sample_products) -> None:
    trainer = MagicMock()
    trainer.train.return_value = TrainingResult(
        model=LogisticRegression(),
        scaler=StandardScaler(),
        metrics={"accuracy": 0.9, "roc_auc": 0.8},
        validated_customers=2,
    )
    handler = ModelHandler(model_trainer=trainer)
    result = handler.train_and_persist(
        sample_events,
        sample_products,
        output_dir=tmp_path,
        version="test-version",
    )
    assert result.artifact_path.exists()
    assert result.model_card_path.exists()


def test_train_and_persist_with_real_data(tmp_path: Path) -> None:
    events = pd.read_csv("data/events.csv")
    products = pd.read_csv("data/products.csv")
    result = ModelHandler().train_and_persist(
        events,
        products,
        output_dir=tmp_path,
        version="test-version",
    )
    assert result.training_result.validated_customers > 0
