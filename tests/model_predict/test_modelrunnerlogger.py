import logging

from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


def test_configure_attaches_stream_handler() -> None:
    ModelRunnerLogger._configured = False
    logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE).handlers.clear()

    ModelRunnerLogger.configure()

    logger = logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE)
    handler_names = [handler.__class__.__name__ for handler in logger.handlers]

    assert "StreamHandler" in handler_names


def test_logger_emits_json_message(capsys) -> None:
    ModelRunnerLogger._configured = False
    logging.getLogger(ModelRunnerLogger.LOG_NAMESPACE).handlers.clear()
    ModelRunnerLogger.configure()

    logger = ModelRunnerLogger("test_component")
    logger.info("unit_test_event", status="ok")

    captured = capsys.readouterr()
    assert "unit_test_event" in captured.out
    assert "test_component" in captured.out
