"""Gateway orchestrating drift monitoring use cases."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from model_drift_monitor.domain.entities.model import ModelPredictionSnapshot
from model_drift_monitor.domain.gateways.awsconnector import AwsConnector
from model_drift_monitor.domain.usecases.calltrainpipeline import CallTrainPipeline
from model_drift_monitor.domain.usecases.datadriftchecker import DataDriftChecker
from model_drift_monitor.domain.usecases.precisioncalculator import PrecisionCalculator
from model_drift_monitor.domain.usecases.recallcalculator import RecallCalculator
from model_drift_monitor.domain.utils.modeldriftlogger import ModelDriftLogger


@dataclass(frozen=True)
class MonitoringResult:
    """Summary returned after a drift monitoring run."""

    predictions_s3_uri: str
    monitoring_s3_uri: str
    precision: float
    recall: float
    data_drift_detected: bool
    performance_drift_detected: bool
    retrain_triggered: bool
    evaluated_rows: int


class MetricsHandler:
    """Coordinate performance and drift checks over a prediction snapshot."""

    PURCHASE_EVENT = "purchase"

    def __init__(
        self,
        aws_connector: AwsConnector | None = None,
        precision_calculator: PrecisionCalculator | None = None,
        recall_calculator: RecallCalculator | None = None,
        data_drift_checker: DataDriftChecker | None = None,
        call_train_pipeline: CallTrainPipeline | None = None,
    ) -> None:
        self.aws_connector = aws_connector or AwsConnector()
        self.precision_calculator = precision_calculator or PrecisionCalculator()
        self.recall_calculator = recall_calculator or RecallCalculator()
        self.data_drift_checker = data_drift_checker or DataDriftChecker()
        self.call_train_pipeline = call_train_pipeline or CallTrainPipeline(
            self.aws_connector
        )
        self.logger = ModelDriftLogger(self.__class__.__name__)

    def run(
        self,
        predictions: pd.DataFrame,
        events: pd.DataFrame,
        products: pd.DataFrame,
        predictions_s3_uri: str,
        run_hash: str,
        monitoring_bucket: str,
        monitoring_prefix: str,
        local_output_dir: str,
        sns_topic_arn: str = "",
    ) -> MonitoringResult:
        """Execute monitoring, persist metrics and optionally trigger retraining."""
        validated_predictions = ModelPredictionSnapshot.validate_dataframe(predictions)
        evaluation_frame = self._build_evaluation_frame(validated_predictions, events)

        precision = self.precision_calculator.calculate(evaluation_frame)
        recall = self.recall_calculator.calculate(evaluation_frame)
        performance_drift_detected = (
            precision < CallTrainPipeline.PERFORMANCE_THRESHOLD
            or recall < CallTrainPipeline.PERFORMANCE_THRESHOLD
        )

        training_features = self.data_drift_checker.build_training_features(events, products)
        drift_result = self.data_drift_checker.check(
            training_features=training_features,
            prediction_features=validated_predictions,
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        monitoring_filename = f"model_performance_{run_hash}_{timestamp}.parquet"
        summary = pd.DataFrame(
            [
                {
                    "predictions_s3_uri": predictions_s3_uri,
                    "run_hash": run_hash,
                    "monitored_at": datetime.now(timezone.utc).isoformat(),
                    "precision": precision,
                    "recall": recall,
                    "performance_drift_detected": performance_drift_detected,
                    "data_drift_detected": drift_result.drift_detected,
                    "evaluated_rows": len(evaluation_frame),
                    "positive_labels": int(evaluation_frame["actual_purchase"].sum()),
                    "predicted_positives": int(evaluation_frame["predicted_purchase"].sum()),
                    "feature_drift_details": json.dumps(
                        drift_result.to_records(),
                        ensure_ascii=False,
                    ),
                }
            ]
        )

        monitoring_s3_uri = self.aws_connector.upload_monitoring_report(
            report=summary,
            bucket=monitoring_bucket,
            prefix=monitoring_prefix,
            filename=monitoring_filename,
            local_dir=local_output_dir,
        )

        retrain_triggered = False
        should_retrain = self.call_train_pipeline.should_retrain(
            precision=precision,
            recall=recall,
            data_drift_detected=drift_result.drift_detected,
        )

        if drift_result.drift_detected and sns_topic_arn:
            self.aws_connector.publish_drift_notification(
                topic_arn=sns_topic_arn,
                subject="Model drift detected in personalization pipeline",
                payload={
                    "predictions_s3_uri": predictions_s3_uri,
                    "precision": precision,
                    "recall": recall,
                    "data_drift_detected": True,
                    "feature_drift": drift_result.to_records(),
                },
            )

        if should_retrain:
            self.call_train_pipeline.trigger()
            retrain_triggered = True
            if sns_topic_arn:
                self.aws_connector.publish_drift_notification(
                    topic_arn=sns_topic_arn,
                    subject="Model retraining triggered by drift monitor",
                    payload={
                        "predictions_s3_uri": predictions_s3_uri,
                        "precision": precision,
                        "recall": recall,
                        "performance_drift_detected": performance_drift_detected,
                        "data_drift_detected": drift_result.drift_detected,
                        "retrain_triggered": True,
                    },
                )

        self.logger.info(
            "monitoring_completed",
            precision=precision,
            recall=recall,
            data_drift_detected=drift_result.drift_detected,
            performance_drift_detected=performance_drift_detected,
            retrain_triggered=retrain_triggered,
            monitoring_s3_uri=monitoring_s3_uri,
        )

        return MonitoringResult(
            predictions_s3_uri=predictions_s3_uri,
            monitoring_s3_uri=monitoring_s3_uri,
            precision=precision,
            recall=recall,
            data_drift_detected=drift_result.drift_detected,
            performance_drift_detected=performance_drift_detected,
            retrain_triggered=retrain_triggered,
            evaluated_rows=len(evaluation_frame),
        )

    def _build_evaluation_frame(
        self,
        predictions: pd.DataFrame,
        events: pd.DataFrame,
    ) -> pd.DataFrame:
        """Join predictions with purchase events to build the evaluation dataset."""
        observed_pairs = events[["user_id", "product_id"]].drop_duplicates()
        purchase_pairs = (
            events.loc[events["event_type"] == self.PURCHASE_EVENT, ["user_id", "product_id"]]
            .drop_duplicates()
            .assign(actual_purchase=1)
        )

        evaluation = observed_pairs.merge(
            predictions[
                ["user_id", "product_id", "recommendation_score"]
            ],
            on=["user_id", "product_id"],
            how="inner",
        )
        evaluation = evaluation.merge(
            purchase_pairs,
            on=["user_id", "product_id"],
            how="left",
        )
        evaluation["actual_purchase"] = evaluation["actual_purchase"].fillna(0).astype(int)
        evaluation["predicted_purchase"] = (
            evaluation["recommendation_score"] > PrecisionCalculator.SCORE_THRESHOLD
        ).astype(int)
        return evaluation
