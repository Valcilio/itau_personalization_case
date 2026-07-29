"""Shared fixtures for live AWS integration tests."""

from __future__ import annotations

import pytest

from tests.helpers.aws_integration import (
    has_aws_credentials,
    integration_run_id as build_integration_run_id,
    load_terraform_outputs,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def terraform_outputs(_aws_available) -> dict[str, str]:
    """Load deployed infrastructure outputs from Terraform."""
    return load_terraform_outputs()


@pytest.fixture(scope="session")
def _aws_available() -> None:
    """Skip the integration suite when AWS credentials are unavailable."""
    if not has_aws_credentials():
        pytest.skip("AWS credentials are not configured for integration tests.")


@pytest.fixture(scope="session")
def integration_run_id() -> str:
    """Unique id used to isolate integration artifacts in AWS."""
    return build_integration_run_id()
