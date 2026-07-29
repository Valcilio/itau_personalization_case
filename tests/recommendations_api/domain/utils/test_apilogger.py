"""Unit tests for recommendations_api.domain.utils.apilogger."""

import logging
from unittest.mock import patch

import pytest

from recommendations_api.domain.utils.apilogger import ApiLogger


def test_configure_attaches_stream_handler() -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure()
    logger = logging.getLogger(ApiLogger.LOG_NAMESPACE)
    assert "StreamHandler" in [handler.__class__.__name__ for handler in logger.handlers]


def test_info_emits_json_message(capsys) -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure()
    ApiLogger("component").info("unit_test_event", status="ok")
    assert "unit_test_event" in capsys.readouterr().out


def test_build_cloudwatch_handler_returns_none_on_ecs(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDWATCH_LOG_GROUP", "group")
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI", "uri")
    handler = ApiLogger._build_cloudwatch_handler(logging.INFO, logging.Formatter("%(message)s"))
    assert handler is None


def test_running_on_ecs_detects_metadata(monkeypatch) -> None:
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "uri")
    assert ApiLogger._running_on_ecs() is True


def test_debug_warning_error_and_exception(capsys) -> None:
    ApiLogger._configured = False
    logging.getLogger(ApiLogger.LOG_NAMESPACE).handlers.clear()
    ApiLogger.configure(level=logging.DEBUG)
    logger = ApiLogger("component")
    logger.debug("debug_event")
    logger.warning("warning_event")
    logger.error("error_event")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("exception_event")
    output = capsys.readouterr().out
    assert "debug_event" in output
    assert "exception_event" in output


def test_build_cloudwatch_handler_requires_watchtower(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDWATCH_LOG_GROUP", "group")
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI", raising=False)
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI_V4", raising=False)
    with patch("recommendations_api.domain.utils.apilogger.watchtower", None):
        with pytest.raises(ImportError):
            ApiLogger._build_cloudwatch_handler(logging.INFO, logging.Formatter("%(message)s"))
