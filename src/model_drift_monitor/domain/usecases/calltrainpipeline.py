"""Use case responsible for triggering the model training pipeline."""

from typing import Any, Protocol

from model_drift_monitor.domain.utils.modeldriftlogger import ModelDriftLogger


class TrainingPipelineClient(Protocol):
    """Protocol implemented by AWS gateways that can launch model_train."""

    def run_model_train_task(self) -> dict[str, Any]:
        """Start a one-off model_train ECS task."""


class CallTrainPipeline:
    """Trigger model retraining when monitoring thresholds are breached."""

    PERFORMANCE_THRESHOLD = 0.5

    def __init__(self, aws_client: TrainingPipelineClient) -> None:
        self.aws_client = aws_client
        self.logger = ModelDriftLogger(self.__class__.__name__)

    def should_retrain(
        self,
        precision: float,
        recall: float,
        data_drift_detected: bool,
    ) -> bool:
        """Return True when performance or data drift requires retraining."""
        performance_drift = (
            precision < self.PERFORMANCE_THRESHOLD or recall < self.PERFORMANCE_THRESHOLD
        )
        return performance_drift or data_drift_detected

    def trigger(self) -> dict[str, Any]:
        """Launch the model_train ECS task."""
        self.logger.info("model_train_trigger_started")
        response = self.aws_client.run_model_train_task()
        self.logger.info("model_train_trigger_completed", task_arn=response.get("taskArn", ""))
        return response
