"""Unit tests for model_train.main."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from model_train.main import (
    PipelineResult,
    TrainingMetrics,
    load_config,
    load_datasets,
    main,
    publish_model_artifact,
    register_model_version,
    resolve_baseline_model_dir,
    run_training_pipeline,
    seed_baseline_model_if_needed,
)


def test_load_config_requires_image_tag(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_TAG", raising=False)
    with pytest.raises(ValueError, match="IMAGE_TAG"):
        load_config()


def test_load_config_returns_version(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_TAG", "v1")
    config = load_config()
    assert config["model_version"] == "v1"


def test_load_datasets_reads_csv(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_TAG", "v1")
    events_path = tmp_path / "events.csv"
    products_path = tmp_path / "products.csv"
    pd.DataFrame({"user_id": ["u_1"]}).to_csv(events_path, index=False)
    pd.DataFrame({"product_id": ["p_1"]}).to_csv(products_path, index=False)
    aws = MagicMock()
    aws.download_training_dataset.return_value = {
        "events": events_path,
        "products": products_path,
    }
    config = load_config()
    config["data_bucket"] = "bucket"
    events, products = load_datasets(config, aws)
    assert len(events) == 1
    assert len(products) == 1


def test_publish_model_artifact_skips_without_bucket(tmp_path: Path) -> None:
    (tmp_path / "model.pkl").write_bytes(b"x")
    uri = publish_model_artifact(tmp_path, {"model_bucket": ""}, MagicMock())
    assert uri.endswith("model.pkl")


def test_publish_model_artifact_uploads_when_configured(tmp_path: Path) -> None:
    (tmp_path / "model.pkl").write_bytes(b"x")
    aws = MagicMock()
    aws.upload_model_directory.return_value = "s3://bucket/model.tar.gz"
    uri = publish_model_artifact(
        tmp_path,
        {"model_bucket": "bucket", "model_prefix": "models/v1"},
        aws,
    )
    assert uri == "s3://bucket/model.tar.gz"


def test_register_model_version_skips_without_image() -> None:
    assert register_model_version("s3://x", {"model_bucket": "", "inference_image_uri": ""}, MagicMock()) == ""


def test_register_model_version_registers_package() -> None:
    aws = MagicMock()
    aws.register_model_package.return_value = "arn:package"
    arn = register_model_version(
        "s3://bucket/model.tar.gz",
        {
            "model_bucket": "bucket",
            "inference_image_uri": "image",
            "model_package_group_name": "group",
            "model_version": "v1",
        },
        aws,
    )
    assert arn == "arn:package"


@patch("model_train.main.ModelTrainerLogger.configure")
@patch("model_train.main.run_training_pipeline")
def test_main_returns_zero(mock_run, _mock_configure) -> None:
    mock_run.return_value = PipelineResult(
        model_version="v1",
        model_output_dir="/tmp",
        model_s3_uri="s3://x",
        model_package_arn="arn",
        baseline_model_package_arn=None,
        metrics=TrainingMetrics(accuracy="0.9", roc_auc="0.8"),
        validated_customers=1,
    )
    assert main() == 0


@patch("model_train.main.register_model_version", return_value="arn")
@patch("model_train.main.publish_model_artifact", return_value="s3://model")
@patch("model_train.main.seed_baseline_model_if_needed", return_value=None)
@patch("model_train.main.load_datasets")
@patch("model_train.main.load_config")
@patch("model_train.main.AwsConnector")
@patch("model_train.main.ModelHandler")
def test_run_training_pipeline(
    mock_handler_cls,
    _mock_connector_cls,
    mock_load_config,
    mock_load_datasets,
    mock_seed,
    _mock_publish,
    _mock_register,
) -> None:
    mock_load_config.return_value = {
        "model_version": "v1",
        "model_output_dir": "/tmp/model",
        "data_bucket": "bucket",
        "data_prefix": "data",
        "training_data_dir": "/tmp/training",
    }
    mock_load_datasets.return_value = (pd.DataFrame(), pd.DataFrame())
    mock_handler_cls.return_value.train_and_persist.return_value = MagicMock(
        training_result=MagicMock(
            metrics={"accuracy": 0.9, "roc_auc": 0.8},
            validated_customers=10,
        )
    )
    result = run_training_pipeline()
    assert result.model_version == "v1"
    assert result.validated_customers == 10
    mock_seed.assert_called_once()


def test_resolve_baseline_model_dir_uses_repo_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_TAG", "run-1")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.pkl").write_bytes(b"x")
    monkeypatch.setenv("BASELINE_MODEL_DIR", str(model_dir))
    config = load_config()
    assert resolve_baseline_model_dir(config) == model_dir


def test_seed_baseline_model_if_needed_skips_when_registry_not_empty() -> None:
    aws = MagicMock()
    aws.has_model_packages.return_value = True
    arn = seed_baseline_model_if_needed(
        {
            "model_bucket": "bucket",
            "inference_image_uri": "image",
            "model_package_group_name": "group",
            "model_output_dir": "/tmp/model",
        },
        aws,
    )
    assert arn is None
    aws.upload_model_directory.assert_not_called()


def test_seed_baseline_model_if_needed_registers_case_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMAGE_TAG", "run-1")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.pkl").write_bytes(b"model")
    (model_dir / "model_card.json").write_text("{}", encoding="utf-8")

    aws = MagicMock()
    aws.has_model_packages.return_value = False
    aws.upload_model_directory.return_value = "s3://bucket/baseline/model.tar.gz"
    aws.register_model_package.return_value = "arn:baseline"

    config = load_config()
    config.update(
        {
            "model_bucket": "bucket",
            "inference_image_uri": "image",
            "model_package_group_name": "group",
            "model_output_dir": str(tmp_path / "output"),
            "baseline_model_dir": str(model_dir),
        }
    )

    arn = seed_baseline_model_if_needed(config, aws)
    assert arn == "arn:baseline"
    aws.register_model_package.assert_called_once()
