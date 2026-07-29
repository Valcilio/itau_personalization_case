"""Unit tests for recommendations_api.domain.gateways.awsconnector."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from recommendations_api.domain.gateways.awsconnector import AwsConnector


@pytest.fixture
def connector(monkeypatch) -> AwsConnector:
    monkeypatch.setenv("PREDICTIONS_DYNAMODB_TABLE", "predictions-table")
    monkeypatch.setenv("DATA_BUCKET", "data-bucket")
    with patch("recommendations_api.domain.gateways.awsconnector.boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        yield AwsConnector(region_name="us-east-1")


def test_get_user_predictions_queries_dynamodb(connector: AwsConnector) -> None:
    connector.dynamodb_client.query.return_value = {
        "Items": [
            {
                "user_id": {"S": "u_0231"},
                "product_id": {"S": "p_001"},
                "recommendation_score": {"N": "0.9"},
                "interactions": {"N": "1"},
                "price": {"N": "10"},
                "avg_rating": {"N": "4"},
                "popularity_score": {"N": "0.8"},
                "user_affinity_match": {"N": "1"},
                "is_cold_start": {"BOOL": False},
            }
        ]
    }
    connector.s3_client.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"product_id,category\np_001,livros\n")
    }
    frame = connector.get_user_predictions("u_0231")
    assert len(frame) == 1
    assert frame.iloc[0]["product_id"] == "p_001"


def test_get_cold_start_predictions_uses_catalog(connector: AwsConnector) -> None:
    connector.s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=lambda: (
                "product_id,category,price,avg_rating,popularity_score\n"
                "p_001,livros,10,4.5,0.9\n"
                "p_002,moda,20,4.0,0.4\n"
            ).encode()
        )
    }
    frame = connector.get_cold_start_predictions(1)
    assert len(frame) == 1
    assert frame.iloc[0]["recommendation_score"] == frame.iloc[0]["popularity_score"]


def test_get_products_catalog_caches_s3_download(connector: AwsConnector) -> None:
    connector.s3_client.get_object.return_value = {
        "Body": MagicMock(
            read=lambda: b"product_id,category,price,avg_rating,popularity_score\np_001,livros,10,4,0.9\n"
        )
    }
    first = connector.get_products_catalog()
    second = connector.get_products_catalog()
    assert len(first) == len(second)
    connector.s3_client.get_object.assert_called_once()


def test_init_requires_predictions_table(monkeypatch) -> None:
    monkeypatch.delenv("PREDICTIONS_DYNAMODB_TABLE", raising=False)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    with pytest.raises(ValueError, match="PREDICTIONS_DYNAMODB_TABLE"):
        AwsConnector()
