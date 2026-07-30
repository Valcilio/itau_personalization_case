"""Unit tests for drift monitoring use cases."""

import pandas as pd

from model_drift_monitor.domain.usecases.datadriftchecker import DataDriftChecker
from model_drift_monitor.domain.usecases.precisioncalculator import PrecisionCalculator
from model_drift_monitor.domain.usecases.recallcalculator import RecallCalculator


def test_precision_and_recall_on_labeled_frame() -> None:
    evaluation = pd.DataFrame(
        {
            "actual_purchase": [1, 1, 0, 0],
            "predicted_purchase": [1, 0, 0, 1],
        }
    )
    precision = PrecisionCalculator().calculate(evaluation)
    recall = RecallCalculator().calculate(evaluation)
    assert precision == 0.5
    assert recall == 0.5


def test_data_drift_checker_detects_large_median_shift() -> None:
    checker = DataDriftChecker()
    training = pd.DataFrame(
        {
            "interactions": [1, 2, 3],
            "price": [10.0, 11.0, 12.0],
            "avg_rating": [4.0, 4.1, 4.2],
            "popularity_score": [0.1, 0.2, 0.3],
            "user_affinity_match": [0, 1, 0],
        }
    )
    prediction = pd.DataFrame(
        {
            "interactions": [100, 120, 140],
            "price": [100.0, 110.0, 120.0],
            "avg_rating": [1.0, 1.5, 2.0],
            "popularity_score": [0.9, 0.95, 0.99],
            "user_affinity_match": [1, 1, 1],
        }
    )
    result = checker.check(training, prediction)
    assert result.drift_detected is True
    assert any(report.median_drift_detected for report in result.feature_reports)
