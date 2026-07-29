"""Gateway that loads the model artifact and orchestrates inference."""

import pickle
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from model_predict.domain.usecases.featureengineer import FeatureEngineer
from model_predict.domain.usecases.modelrunner import ModelRunner
from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


@dataclass(frozen=True)
class LoadedArtifact:
    """Model components extracted from the SageMaker model package artifact."""

    model: LogisticRegression
    scaler: StandardScaler
    feature_cols: list[str]


@dataclass(frozen=True)
class HandlerResult:
    """Predictions produced by ``ModelHandler.run_predictions``."""

    predictions: pd.DataFrame
    validated_costumers: int


class ModelHandler:
    """Extract artifact contents and run feature engineering plus inference.

    ``ModelHandler`` loads ``model.pkl`` from the extracted model package, builds
    features through ``FeatureEngineer`` and scores them with ``ModelRunner``.
    """

    MODEL_FILENAME = "model.pkl"

    def __init__(self) -> None:
        """Initialize the prediction handler."""
        self.logger = ModelRunnerLogger(self.__class__.__name__)

    def load_artifact(self, artifact_dir: str | Path) -> LoadedArtifact:
        """Load model and scaler from an extracted model package directory.

        The training pipeline stores both objects inside ``model.pkl`` along with
        the expected feature column order.

        Args:
            artifact_dir: Directory containing ``model.pkl``.

        Returns:
            Loaded classifier, scaler and feature column names.

        Raises:
            FileNotFoundError: If ``model.pkl`` is missing.
            ValueError: If the pickle payload is missing required keys.
        """
        artifact_path = Path(artifact_dir) / self.MODEL_FILENAME
        if not artifact_path.exists():
            raise FileNotFoundError(f"Missing model artifact: {artifact_path}")

        self.logger.info("model_artifact_load_started", artifact_path=str(artifact_path))
        with artifact_path.open("rb") as artifact_file:
            payload = pickle.load(artifact_file)

        required_keys = {"model", "scaler", "feature_cols"}
        missing_keys = required_keys.difference(payload)
        if missing_keys:
            raise ValueError(f"Model artifact missing keys: {sorted(missing_keys)}")

        loaded = LoadedArtifact(
            model=payload["model"],
            scaler=payload["scaler"],
            feature_cols=list(payload["feature_cols"]),
        )
        self.logger.info(
            "model_artifact_load_completed",
            feature_cols=loaded.feature_cols,
        )
        return loaded

    def run_predictions(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
        artifact_dir: str | Path,
    ) -> HandlerResult:
        """Build features and generate purchase probabilities.

        Args:
            events: Historical user interaction events.
            products: Product catalog.
            artifact_dir: Directory containing the extracted ``model.pkl``.

        Returns:
            Predictions dataframe and number of validated costumer rows.
        """
        self.logger.info(
            "prediction_pipeline_stage_started",
            stage="run_predictions",
            events_rows=len(events),
            products_rows=len(products),
            artifact_dir=str(artifact_dir),
        )

        artifact = self.load_artifact(artifact_dir)
        feature_engineer = FeatureEngineer(
            events=events,
            products=products,
            scaler=artifact.scaler,
        )
        features, scaled_features = feature_engineer.build()

        model_runner = ModelRunner(model=artifact.model)
        predictions = model_runner.run(features, scaled_features)

        self.logger.info(
            "prediction_pipeline_stage_completed",
            stage="run_predictions",
            prediction_rows=len(predictions),
        )
        return HandlerResult(
            predictions=predictions,
            validated_costumers=len(features),
        )
