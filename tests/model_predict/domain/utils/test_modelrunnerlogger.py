"""Unit tests for model_predict.domain.utils.modelrunnerlogger."""

import logging

from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


def test_configure_attaches_stream_handler() -> None:
    ModelRunnerLogger._configured = False
    logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE).handlers.clear()
    ModelRunnerLogger.configure()
    logger = logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE)
    assert "StreamHandler" in [handler.__class__.__name__ for handler in logger.handlers]


def test_info_emits_json_message(capsys) -> None:
    ModelRunnerLogger._configured = False
    logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE).handlers.clear()
    ModelRunnerLogger.configure()
    ModelRunnerLogger("component").info("unit_test_event", status="ok")
    captured = capsys.readouterr()
    assert "unit_test_event" in captured.out


def test_debug_warning_error_and_exception(capsys) -> None:
    ModelRunnerLogger._configured = False
    logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE).handlers.clear()
    ModelRunnerLogger.configure(level=logging.DEBUG)
    logger = ModelRunnerLogger("component")
    logger.debug("debug_event")
    logger.warning("warning_event")
    logger.error("error_event")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("exception_event")
    captured = capsys.readouterr()
    assert "debug_event" in captured.out
    assert "warning_event" in captured.out
    assert "error_event" in captured.out
    assert "exception_event" in captured.out
