"""Domain entity used to validate prediction snapshots for drift monitoring."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ModelPredictionSnapshot:
    """Validate the schema of a model prediction dataframe."""

    FEATURE_COLUMNS = [
        "interactions",
        "price",
        "avg_rating",
        "popularity_score",
        "user_affinity_match",
    ]
    REQUIRED_COLUMNS = [
        "user_id",
        "product_id",
        "recommendation_score",
        *FEATURE_COLUMNS,
    ]

    @classmethod
    def validate_dataframe(cls, predictions: pd.DataFrame) -> pd.DataFrame:
        """Ensure the prediction snapshot matches the expected contract.

        Args:
            predictions: Raw prediction output loaded from S3.

        Returns:
            Validated copy with normalized dtypes.

        Raises:
            ValueError: If required columns are missing or values are invalid.
        """
        missing_columns = [
            column for column in cls.REQUIRED_COLUMNS if column not in predictions.columns
        ]
        if missing_columns:
            raise ValueError(f"Missing required prediction columns: {missing_columns}")

        if predictions.empty:
            raise ValueError("predictions dataframe is empty")

        validated = predictions.copy()
        validated["user_id"] = validated["user_id"].astype(str)
        validated["product_id"] = validated["product_id"].astype(str)
        validated["recommendation_score"] = validated["recommendation_score"].astype(float)

        for column in cls.FEATURE_COLUMNS:
            validated[column] = validated[column].astype(float)

        if (validated["recommendation_score"] < 0).any() or (
            validated["recommendation_score"] > 1
        ).any():
            raise ValueError("recommendation_score must be between 0 and 1")

        if (validated["interactions"] < 0).any():
            raise ValueError("interactions must be >= 0")

        if (validated["price"] <= 0).any():
            raise ValueError("price must be > 0")

        if ((validated["avg_rating"] < 0) | (validated["avg_rating"] > 5)).any():
            raise ValueError("avg_rating must be between 0 and 5")

        if ((validated["popularity_score"] < 0) | (validated["popularity_score"] > 1)).any():
            raise ValueError("popularity_score must be between 0 and 1")

        affinity_values = set(validated["user_affinity_match"].astype(int).unique())
        if not affinity_values.issubset({0, 1}):
            raise ValueError("user_affinity_match must be 0 or 1")

        return validated
