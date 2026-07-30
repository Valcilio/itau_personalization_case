"""Unit tests for model_drift_monitor.main."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from model_drift_monitor.main import extract_run_hash, load_config, main


def test_extract_run_hash_parses_predictions_filename() -> None:
    assert extract_run_hash("predictions_20250101120000_a1b2c3d4.csv") == "a1b2c3d4"


def test_extract_run_hash_rejects_invalid_filename() -> None:
    with pytest.raises(ValueError, match="PREDICTIONS_FILENAME"):
        extract_run_hash("invalid.csv")


def test_load_config_requires_predictions_uri(monkeypatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "data-bucket")
    monkeypatch.delenv("PREDICTIONS_S3_URI", raising=False)
    with pytest.raises(ValueError, match="PREDICTIONS_S3_URI"):
        load_config()


def test_load_config_returns_expected_keys(monkeypatch) -> None:
    monkeypatch.setenv("DATA_BUCKET", "data-bucket")
    monkeypatch.setenv(
        "PREDICTIONS_S3_URI",
        "s3://data-bucket/predictions/predictions_20250101120000_a1b2c3d4.csv",
    )
    monkeypatch.setenv("PREDICTIONS_FILENAME", "predictions_20250101120000_a1b2c3d4.csv")
    config = load_config()
    assert config["run_hash"] == "a1b2c3d4"
    assert config["monitoring_prefix"] == "model-performance"


@patch("model_drift_monitor.main.ModelDriftLogger.configure")
@patch("model_drift_monitor.main.run_monitoring_pipeline")
def test_main_returns_zero_on_success(mock_run, _mock_configure, capsys) -> None:
    mock_run.return_value = {
        "precision": 0.8,
        "recall": 0.7,
        "data_drift_detected": False,
        "retrain_triggered": False,
    }
    assert main() == 0
    assert "precision" in capsys.readouterr().out
