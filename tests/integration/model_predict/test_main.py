"""Live AWS integration test for model_predict."""

from __future__ import annotations

import boto3
import pytest

from model_predict.main import run_prediction_pipeline

from tests.helpers.aws_integration import (
    dynamodb_table_has_items,
    model_predict_env,
    s3_object_exists,
    temporary_env,
)

pytestmark = [pytest.mark.integration, pytest.mark.order(2)]


@pytest.mark.usefixtures("production_model_registry_ready")
def test_run_prediction_pipeline_against_aws(terraform_outputs, integration_run_id) -> None:
    """Run the full prediction pipeline using real S3, SageMaker and DynamoDB."""
    env = model_predict_env(terraform_outputs, integration_run_id)
    table_name = env["PREDICTIONS_DYNAMODB_TABLE"]
    production_table = terraform_outputs["predictions_dynamodb_table_name"]

    with temporary_env(env):
        result = run_prediction_pipeline()

    assert table_name != production_table

    assert result.prediction_rows > 0
    assert result.validated_costumers > 0
    assert result.predictions_s3_uri.startswith("s3://")
    assert s3_object_exists(result.predictions_s3_uri)
    assert result.predictions_dynamodb_table == table_name
    assert dynamodb_table_has_items(table_name)

    dynamodb = boto3.client("dynamodb")
    query = dynamodb.query(
        TableName=table_name,
        KeyConditionExpression="user_id = :user_id",
        ExpressionAttributeValues={":user_id": {"S": "u_0231"}},
        Limit=1,
    )
    assert query.get("Items"), "Expected predictions for user u_0231 in DynamoDB"
