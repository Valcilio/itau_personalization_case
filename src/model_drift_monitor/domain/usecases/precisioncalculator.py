"""Use case responsible for computing model precision."""

import pandas as pd
from sklearn.metrics import precision_score


class PrecisionCalculator:
    """Compute precision for binary purchase predictions."""

    SCORE_THRESHOLD = 0.5

    def calculate(self, evaluation_frame: pd.DataFrame) -> float:
        """Calculate precision using purchase events as ground truth.

        Args:
            evaluation_frame: Rows with ``actual_purchase`` and ``predicted_purchase``.

        Returns:
            Precision score in the range [0, 1].
        """
        if evaluation_frame.empty:
            return 0.0

        y_true = evaluation_frame["actual_purchase"].astype(int)
        y_pred = evaluation_frame["predicted_purchase"].astype(int)
        return float(precision_score(y_true, y_pred, zero_division=0))

    def build_binary_predictions(self, predictions: pd.DataFrame) -> pd.Series:
        """Convert recommendation scores into binary purchase predictions."""
        return (predictions["recommendation_score"] > self.SCORE_THRESHOLD).astype(int)
