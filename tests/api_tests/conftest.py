"""Fixtures for live API Gateway tests."""

from __future__ import annotations

import pytest

from tests.helpers.api_gateway import (
    API_STAGE,
    build_api_client,
    cold_start_user_id,
    known_user_id,
    load_api_gateway_config,
    wait_for_api_health,
)
from tests.helpers.aws_integration import (
    ensure_production_predictions,
    has_aws_credentials,
    load_terraform_outputs,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def _aws_available() -> None:
    """Skip API tests when AWS credentials are unavailable."""
    if not has_aws_credentials():
        pytest.skip("AWS credentials are not configured for API tests.")


@pytest.fixture(scope="session")
def terraform_outputs(_aws_available) -> dict[str, str]:
    """Load deployed infrastructure outputs from Terraform."""
    return load_terraform_outputs()


@pytest.fixture(scope="session")
def api_gateway_config(terraform_outputs) -> tuple[str, str]:
    """Return ``(base_url, api_key)`` for the public recommendations API."""
    return load_api_gateway_config(terraform_outputs)


@pytest.fixture(scope="session")
def api_client(api_gateway_config, production_predictions_ready):
    """HTTP client for the deployed recommendations API."""
    base_url, api_key = api_gateway_config
    wait_for_api_health(base_url, api_key)
    with build_api_client(base_url, api_key) as client:
        yield client


@pytest.fixture(scope="session")
def api_base_url(api_gateway_config) -> str:
    """Public API base URL including REST stage."""
    return api_gateway_config[0]


@pytest.fixture(scope="session")
def known_user() -> str:
    """Primary user with event history."""
    return known_user_id()


@pytest.fixture(scope="session")
def cold_start_user() -> str:
    """User id expected to trigger cold start."""
    return cold_start_user_id()


@pytest.fixture(scope="session")
def api_stage() -> str:
    """REST API stage name."""
    return API_STAGE


@pytest.fixture(scope="session")
def production_predictions_ready(terraform_outputs) -> str:
    """Ensure the production predictions table is populated for live API tests."""
    return ensure_production_predictions(terraform_outputs)
