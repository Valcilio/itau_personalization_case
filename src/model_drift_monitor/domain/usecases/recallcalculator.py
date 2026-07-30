"""Use case responsible for computing model recall."""

import pandas as pd
from sklearn.metrics import recall_score


class RecallCalculator:
    """Compute recall for binary purchase predictions."""

    def calculate(self, evaluation_frame: pd.DataFrame) -> float:
        """Calculate recall using purchase events as ground truth.

        Args:
            evaluation_frame: Rows with ``actual_purchase`` and ``predicted_purchase``.

        Returns:
            Recall score in the range [0, 1].
        """
        if evaluation_frame.empty:
            return 0.0

        y_true = evaluation_frame["actual_purchase"].astype(int)
        y_pred = evaluation_frame["predicted_purchase"].astype(int)
        return float(recall_score(y_true, y_pred, zero_division=0))
