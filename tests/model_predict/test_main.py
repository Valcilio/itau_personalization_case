"""Unit tests for model_predict.main."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from model_predict.main import (
    PipelineResult,
    build_predictions_filename,
    format_predictions_for_output,
    load_config,
    load_datasets,
    main,
    run_prediction_pipeline,
    validate_predictions_coverage,
)


def test_build_predictions_filename_is_unique() -> None:
    first = build_predictions_filename()
    second = build_predictions_filename()
    assert first.startswith("predictions_")
    assert first.endswith(".csv")
    assert first != second


def test_load_config_requires_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    with pytest.raises(ValueError, match="DATA_BUCKET"):
        load_config()


def test_load_config_returns_expected_keys(monkeypatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "data-bucket")
    monkeypatch.setenv("PREDICTIONS_DYNAMODB_TABLE", "predictions-table")
    config = load_config()
    assert config["data_bucket"] == "data-bucket"
    assert config["predictions_dynamodb_table"] == "predictions-table"


def test_load_datasets_reads_csv_from_downloaded_paths(tmp_path) -> None:
    events_path = tmp_path / "events.csv"
    products_path = tmp_path / "products.csv"
    pd.DataFrame({"user_id": ["u_1"]}).to_csv(events_path, index=False)
    pd.DataFrame({"product_id": ["p_1"]}).to_csv(products_path, index=False)
    aws = MagicMock()
    aws.download_prediction_dataset.return_value = {
        "events": events_path,
        "products": products_path,
    }
    events, products = load_datasets(
        {"data_bucket": "b", "data_prefix": "p", "local_data_dir": str(tmp_path)},
        aws,
    )
    assert len(events) == 1
    assert len(products) == 1


def test_format_predictions_for_output() -> None:
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
    assert "recommendation_score" in formatted.columns
    assert "purchase_proba" not in formatted.columns
    assert formatted["is_cold_start"].eq(False).all()


def test_validate_predictions_coverage_accepts_full_cartesian_product() -> None:
    events = pd.DataFrame({"user_id": ["u_1", "u_2"], "product_id": ["p_1", "p_2"], "event_type": ["view", "view"]})
    products = pd.DataFrame({"product_id": ["p_1", "p_2"], "category": ["moda", "livros"], "price": [1.0, 2.0], "avg_rating": [4.0, 4.0], "popularity_score": [0.5, 0.5]})
    predictions = pd.DataFrame(
        {
            "user_id": ["u_1", "u_1", "u_2", "u_2"],
            "product_id": ["p_1", "p_2", "p_1", "p_2"],
        }
    )
    validate_predictions_coverage(events, products, predictions)


def test_validate_predictions_coverage_rejects_missing_users() -> None:
    events = pd.DataFrame({"user_id": ["u_1", "u_2"], "product_id": ["p_1", "p_1"], "event_type": ["view", "view"]})
    products = pd.DataFrame({"product_id": ["p_1"], "category": ["moda"], "price": [1.0], "avg_rating": [4.0], "popularity_score": [0.5]})
    predictions = pd.DataFrame({"user_id": ["u_1"], "product_id": ["p_1"]})
    with pytest.raises(ValueError, match="missing users"):
        validate_predictions_coverage(events, products, predictions)


@patch("model_predict.main.ModelRunnerLogger.configure")
@patch("model_predict.main.run_prediction_pipeline")
def test_main_returns_zero_on_success(mock_run, _mock_configure, capsys) -> None:
    mock_run.return_value = PipelineResult(
        model_package_group_name="g",
        model_package_version=1,
        predictions_s3_uri="s3://x",
        predictions_dynamodb_table="t",
        prediction_rows=1,
        validated_costumers=1,
    )
    assert main() == 0
    assert "predictions_s3_uri" in capsys.readouterr().out


@patch("model_predict.main.AwsConnector")
@patch("model_predict.main.ModelHandler")
@patch("model_predict.main.load_datasets")
@patch("model_predict.main.load_config")
def test_run_prediction_pipeline_returns_summary(
    mock_load_config,
    mock_load_datasets,
    mock_handler_cls,
    mock_connector_cls,
) -> None:
    mock_connector_cls.HARDCODED_MODEL_PACKAGE_VERSION = 1
    mock_load_config.return_value = {
        "data_bucket": "b",
        "data_prefix": "p",
        "predictions_bucket": "b",
        "predictions_prefix": "pred",
        "predictions_filename": "predictions_test.csv",
        "predictions_dynamodb_table": "table",
        "model_package_group_name": "group",
        "local_data_dir": "/tmp/data",
        "local_model_dir": "/tmp/model",
        "local_output_dir": "/tmp/out",
        "drift_monitor_enabled": True,
        "drift_monitor_cluster": "drift-cluster",
        "drift_monitor_task_definition": "drift-task",
        "drift_monitor_subnets": "subnet-1",
        "drift_monitor_security_group": "sg-1",
    }
    mock_load_datasets.return_value = (pd.DataFrame(), pd.DataFrame())
    connector = mock_connector_cls.return_value
    connector.download_model_artifact.return_value = "/tmp/model"
    connector.upload_predictions.return_value = "s3://b/pred/file.csv"
    handler = mock_handler_cls.return_value
    handler.run_predictions.return_value = MagicMock(
        predictions=pd.DataFrame(
            {
                "user_id": ["u_1", "u_1"],
                "product_id": ["p_1", "p_2"],
                "is_cold_start": [False, False],
                "interactions": [1, 0],
                "price": [10.0, 20.0],
                "avg_rating": [4.0, 3.5],
                "popularity_score": [0.5, 0.2],
                "user_affinity_match": [1, 0],
                "purchase_proba": [0.8, 0.2],
            }
        ),
        validated_costumers=2,
    )
    mock_load_datasets.return_value = (
        pd.DataFrame({"user_id": ["u_1"], "product_id": ["p_1"], "event_type": ["view"]}),
        pd.DataFrame(
            {
                "product_id": ["p_1", "p_2"],
                "category": ["moda", "livros"],
                "price": [10.0, 20.0],
                "avg_rating": [4.0, 3.5],
                "popularity_score": [0.5, 0.2],
            }
        ),
    )

    result = run_prediction_pipeline()
    assert result.prediction_rows == 2
    connector.replace_predictions_table.assert_called_once()
    connector.trigger_drift_monitor_task.assert_called_once()
