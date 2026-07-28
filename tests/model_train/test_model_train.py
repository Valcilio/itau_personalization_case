from pathlib import Path

import pandas as pd
import pytest

from model_train.domain.entities.customer import Customer
from model_train.domain.gateways.modelhandler import ModelHandler


def test_customer_validates_required_features() -> None:
    customer = Customer(
        user_id="u_1",
        product_id="p_1",
        interactions=2,
        price=10.0,
        avg_rating=4.0,
        popularity_score=0.8,
        user_affinity_match=1,
    )

    customer.validate()


def test_customer_rejects_invalid_popularity_score() -> None:
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


def test_build_training_dataset_creates_binary_labels() -> None:
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

    handler = ModelHandler()
    features, labels = handler.build_training_dataset(events, products)

    assert list(handler.FEATURE_COLUMNS) == list(Customer.FEATURE_COLUMNS)
    assert len(features) == 2
    assert labels.tolist() == [1, 0]


def test_model_trainer_validates_features_before_training() -> None:
    events = pd.read_csv("data/events.csv")
    products = pd.read_csv("data/products.csv")
    handler = ModelHandler()

    handler_result = handler.train_and_persist(
        events,
        products,
        output_dir="/tmp/model_train_test_output",
        version="test-version",
    )
    training_result = handler_result.training_result

    assert training_result.validated_customers > 0
    assert "accuracy" in training_result.metrics
    assert "roc_auc" in training_result.metrics


def test_model_handler_saves_artifact(tmp_path: Path) -> None:
    events = pd.read_csv("data/events.csv")
    products = pd.read_csv("data/products.csv")
    handler = ModelHandler()

    handler_result = handler.train_and_persist(
        events,
        products,
        output_dir=tmp_path,
        version="test-version",
    )

    assert handler_result.artifact_path.exists()
    assert handler_result.model_card_path.exists()
