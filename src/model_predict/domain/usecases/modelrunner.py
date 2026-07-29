"""Use case responsible for running purchase propensity inference."""

import pandas as pd
from sklearn.linear_model import LogisticRegression

from model_predict.domain.entities.costumer import Costumer
from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


class ModelRunner:
    """Score each user-product pair with the trained purchase propensity model.

    Receives the fitted classifier and applies it over the scaled feature matrix
    produced by ``FeatureEngineer``, returning the full dataset enriched with
    purchase probabilities.
    """

    FEATURE_COLUMNS = Costumer.FEATURE_COLUMNS
    PROBABILITY_COLUMN = "purchase_proba"

    def __init__(self, model: LogisticRegression) -> None:
        """Initialize the runner.

        Args:
            model: Trained classifier loaded from the model artifact.
        """
        self.model = model
        self.logger = ModelRunnerLogger(self.__class__.__name__)

    def run(
        self,
        features: pd.DataFrame,
        scaled_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """Generate purchase probabilities for every feature row.

        Args:
            features: Dataframe with identifiers and raw feature columns.
            scaled_features: Scaled feature matrix aligned with ``features``.

        Returns:
            Copy of ``features`` with an added ``purchase_proba`` column.
        """
        self.logger.info(
            "model_inference_started",
            rows=len(features),
        )

        probabilities = self.model.predict_proba(
            scaled_features[self.FEATURE_COLUMNS].astype(float)
        )[:, 1]

        predictions = features.copy()
        predictions[self.PROBABILITY_COLUMN] = probabilities

        self.logger.info(
            "model_inference_completed",
            rows=len(predictions),
            min_proba=float(predictions[self.PROBABILITY_COLUMN].min()),
            max_proba=float(predictions[self.PROBABILITY_COLUMN].max()),
        )
        return predictions
