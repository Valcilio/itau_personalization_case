"""Live AWS integration test for model_train."""

from __future__ import annotations

import pytest

from model_train.main import run_training_pipeline

from tests.helpers.aws_integration import (
    model_train_env,
    s3_object_exists,
    temporary_env,
)

pytestmark = [pytest.mark.integration, pytest.mark.order(1)]


def test_run_training_pipeline_against_aws(terraform_outputs, integration_run_id) -> None:
    """Run the full training pipeline using real S3 and SageMaker registry."""
    env = model_train_env(terraform_outputs, integration_run_id)

    with temporary_env(env):
        result = run_training_pipeline()

    assert result.validated_customers > 0
    assert float(result.accuracy) >= 0.0
    assert float(result.roc_auc) >= 0.0
    assert result.model_s3_uri.startswith("s3://")
    assert s3_object_exists(result.model_s3_uri)
    assert result.model_package_arn.startswith("arn:")
