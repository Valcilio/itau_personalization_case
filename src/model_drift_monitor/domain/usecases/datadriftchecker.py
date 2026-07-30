"""Use case responsible for detecting data drift between training and prediction."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from model_drift_monitor.domain.entities.model import ModelPredictionSnapshot


@dataclass(frozen=True)
class FeatureDriftReport:
    """Drift metrics computed for a single feature column."""

    feature: str
    training_median: float
    prediction_median: float
    median_relative_diff: float
    median_drift_detected: bool
    psi: float
    psi_drift_detected: bool
    ks_statistic: float
    ks_p_value: float
    ks_drift_detected: bool
    drift_detected: bool


@dataclass(frozen=True)
class DataDriftResult:
    """Aggregate drift report across all model features."""

    feature_reports: list[FeatureDriftReport]
    drift_detected: bool

    def to_records(self) -> list[dict[str, float | str | bool]]:
        """Serialize per-feature drift metrics for persistence."""
        return [
            {
                "feature": report.feature,
                "training_median": report.training_median,
                "prediction_median": report.prediction_median,
                "median_relative_diff": report.median_relative_diff,
                "median_drift_detected": report.median_drift_detected,
                "psi": report.psi,
                "psi_drift_detected": report.psi_drift_detected,
                "ks_statistic": report.ks_statistic,
                "ks_p_value": report.ks_p_value,
                "ks_drift_detected": report.ks_drift_detected,
                "drift_detected": report.drift_detected,
            }
            for report in self.feature_reports
        ]


class DataDriftChecker:
    """Compare training and prediction feature distributions."""

    FEATURE_COLUMNS = ModelPredictionSnapshot.FEATURE_COLUMNS
    PURCHASE_EVENT = "purchase"
    MEDIAN_DRIFT_THRESHOLD = 0.5
    PSI_DRIFT_THRESHOLD = 0.25
    KS_ALPHA = 0.05
    PSI_BUCKETS = 10

    def build_training_features(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build the feature baseline used during model training."""
        pairs = events[["user_id", "product_id"]].drop_duplicates()
        return self._build_features(events, products, pairs)

    def check(
        self,
        training_features: pd.DataFrame,
        prediction_features: pd.DataFrame,
    ) -> DataDriftResult:
        """Detect drift using median shift, PSI and Kolmogorov-Smirnov tests."""
        reports: list[FeatureDriftReport] = []
        for feature in self.FEATURE_COLUMNS:
            training_values = training_features[feature].astype(float).to_numpy()
            prediction_values = prediction_features[feature].astype(float).to_numpy()

            training_median = float(np.median(training_values))
            prediction_median = float(np.median(prediction_values))
            median_relative_diff = self._relative_difference(
                training_median,
                prediction_median,
            )
            median_drift = median_relative_diff > self.MEDIAN_DRIFT_THRESHOLD

            psi_value = self._population_stability_index(training_values, prediction_values)
            psi_drift = psi_value > self.PSI_DRIFT_THRESHOLD

            ks_result = ks_2samp(training_values, prediction_values, method="auto")
            ks_drift = float(ks_result.pvalue) < self.KS_ALPHA

            drift_detected = median_drift or psi_drift or ks_drift
            reports.append(
                FeatureDriftReport(
                    feature=feature,
                    training_median=training_median,
                    prediction_median=prediction_median,
                    median_relative_diff=median_relative_diff,
                    median_drift_detected=median_drift,
                    psi=psi_value,
                    psi_drift_detected=psi_drift,
                    ks_statistic=float(ks_result.statistic),
                    ks_p_value=float(ks_result.pvalue),
                    ks_drift_detected=ks_drift,
                    drift_detected=drift_detected,
                )
            )

        return DataDriftResult(
            feature_reports=reports,
            drift_detected=any(report.drift_detected for report in reports),
        )

    @staticmethod
    def _relative_difference(reference: float, current: float) -> float:
        denominator = max(abs(reference), 1e-9)
        return abs(current - reference) / denominator

    def _population_stability_index(
        self,
        expected: np.ndarray,
        actual: np.ndarray,
    ) -> float:
        """Compute PSI using quantile buckets derived from the training sample."""
        quantiles = np.linspace(0, 1, self.PSI_BUCKETS + 1)
        breakpoints = np.unique(np.quantile(expected, quantiles))
        if len(breakpoints) < 2:
            return 0.0

        expected_counts, _ = np.histogram(expected, bins=breakpoints)
        actual_counts, _ = np.histogram(actual, bins=breakpoints)

        expected_ratio = expected_counts / max(len(expected), 1)
        actual_ratio = actual_counts / max(len(actual), 1)
        epsilon = 1e-6

        psi_total = 0.0
        for expected_share, actual_share in zip(expected_ratio, actual_ratio, strict=True):
            expected_share = max(float(expected_share), epsilon)
            actual_share = max(float(actual_share), epsilon)
            psi_total += (actual_share - expected_share) * np.log(actual_share / expected_share)
        return float(abs(psi_total))

    def _build_features(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
        pairs: pd.DataFrame,
    ) -> pd.DataFrame:
        interactions = (
            events.groupby(["user_id", "product_id"], as_index=False)
            .size()
            .rename(columns={"size": "interactions"})
        )
        product_features = products[
            ["product_id", "category", "price", "avg_rating", "popularity_score"]
        ]
        top_affinity = self._compute_user_top_affinity_category(events, products)

        features = (
            pairs.merge(interactions, on=["user_id", "product_id"], how="left")
            .merge(product_features, on="product_id", how="left")
            .merge(top_affinity, on="user_id", how="left")
        )
        features["interactions"] = features["interactions"].fillna(0).astype(int)
        features["user_affinity_match"] = (
            features["category"] == features["top_affinity_category"]
        ).astype(int)
        return features[["user_id", "product_id", *self.FEATURE_COLUMNS]]

    def _compute_user_top_affinity_category(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
    ) -> pd.DataFrame:
        events_with_category = events.merge(
            products[["product_id", "category"]],
            on="product_id",
            how="inner",
        )
        category_counts = (
            events_with_category.groupby(["user_id", "category"], as_index=False)
            .size()
            .rename(columns={"size": "interaction_count"})
        )
        return (
            category_counts.sort_values(
                ["user_id", "interaction_count", "category"],
                ascending=[True, False, True],
            )
            .drop_duplicates("user_id")
            .rename(columns={"category": "top_affinity_category"})[
                ["user_id", "top_affinity_category"]
            ]
        )
