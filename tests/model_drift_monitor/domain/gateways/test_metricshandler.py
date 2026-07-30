"""Unit tests for MetricsHandler."""

from unittest.mock import MagicMock

import pandas as pd

from model_drift_monitor.domain.gateways.metricshandler import MetricsHandler


def test_metrics_handler_persists_summary_without_retrain() -> None:
    aws_connector = MagicMock()
    aws_connector.upload_monitoring_report.return_value = (
        "s3://bucket/model-performance/model_performance_abcd1234_20250101120000.parquet"
    )

    handler = MetricsHandler(aws_connector=aws_connector)
    predictions = pd.DataFrame(
        {
            "user_id": ["u_1", "u_1"],
            "product_id": ["p_1", "p_2"],
            "recommendation_score": [0.9, 0.1],
            "interactions": [2, 0],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
            "user_affinity_match": [1, 0],
        }
    )
    events = pd.DataFrame(
        {
            "user_id": ["u_1", "u_1"],
            "product_id": ["p_1", "p_2"],
            "event_type": ["purchase", "view"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": ["p_1", "p_2"],
            "category": ["moda", "livros"],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
        }
    )

    result = handler.run(
        predictions=predictions,
        events=events,
        products=products,
        predictions_s3_uri="s3://bucket/predictions/predictions_20250101120000_abcd1234.csv",
        run_hash="abcd1234",
        monitoring_bucket="bucket",
        monitoring_prefix="model-performance",
        local_output_dir="/tmp/out",
    )

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.retrain_triggered is False
    aws_connector.upload_monitoring_report.assert_called_once()
