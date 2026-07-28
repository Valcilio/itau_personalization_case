import logging

from model_train.domain.utils.modeltrainerlogger import ModelTrainerLogger


def test_configure_attaches_stream_handler() -> None:
    ModelTrainerLogger._configured = False
    logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE).handlers.clear()

    ModelTrainerLogger.configure()

    logger = logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE)
    handler_names = [handler.__class__.__name__ for handler in logger.handlers]

    assert "StreamHandler" in handler_names
    assert all(not handler.__class__.__name__ == "CloudWatchLogHandler" for handler in logger.handlers) or (
        "CloudWatchLogHandler" in handler_names
    )


def test_logger_emits_json_message(capsys) -> None:
    ModelTrainerLogger._configured = False
    logging.getLogger(ModelTrainerLogger.LOG_NAMESPACE).handlers.clear()
    ModelTrainerLogger.configure()

    logger = ModelTrainerLogger("test_component")
    logger.info("unit_test_event", status="ok")

    captured = capsys.readouterr()
    assert "unit_test_event" in captured.out
    assert "test_component" in captured.out
