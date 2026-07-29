"""Unit tests for model_train.domain.utils.modeltrainerlogger."""

import logging

from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


def test_configure_attaches_stream_handler() -> None:
    ModelTrainerLogger._configured = False
    logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE).handlers.clear()
    ModelTrainerLogger.configure()
    logger = logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE)
    assert "StreamHandler" in [handler.__class__.__name__ for handler in logger.handlers]


def test_logger_emits_json_message(capsys) -> None:
    ModelTrainerLogger._configured = False
    logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE).handlers.clear()
    ModelTrainerLogger.configure()
    ModelTrainerLogger("test_component").info("unit_test_event", status="ok")
    captured = capsys.readouterr()
    assert "unit_test_event" in captured.out


def test_debug_warning_error_and_exception(capsys) -> None:
    ModelTrainerLogger._configured = False
    logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE).handlers.clear()
    ModelTrainerLogger.configure(level=logging.DEBUG)
    logger = ModelTrainerLogger("component")
    logger.debug("debug_event")
    logger.warning("warning_event")
    logger.error("error_event")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("exception_event")
    captured = capsys.readouterr()
    assert "debug_event" in captured.out
    assert "exception_event" in captured.out
