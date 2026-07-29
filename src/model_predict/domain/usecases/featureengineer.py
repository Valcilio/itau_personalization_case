"""Use case responsible for building and scaling prediction features."""

import pandas as pd
from sklearn.preprocessing import StandardScaler

from model_predict.domain.entities.costumer import Costumer
from model_predict.domain.utils.modelrunnerlogger import ModelRunnerLogger


class FeatureEngineer:
    """Build model features from events/products and scale them for inference.

    Receives the raw datasets and the fitted scaler as attributes, derives the
    user-product feature matrix expected by the purchase propensity model,
    validates it through ``Costumer`` and returns both raw and scaled features.
    """

    FEATURE_COLUMNS = Costumer.FEATURE_COLUMNS

    def __init__(
        self,
        events: pd.DataFrame,
        products: pd.DataFrame,
        scaler: StandardScaler,
    ) -> None:
        """Initialize the feature engineer.

        Args:
            events: Historical user-product interaction events.
            products: Product catalog used to enrich feature rows.
            scaler: Fitted ``StandardScaler`` loaded from the model artifact.
        """
        self.events = events
        self.products = products
        self.scaler = scaler
        self.logger = ModelRunnerLogger(self.__class__.__name__)

    def build(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Generate validated features and their scaled matrix.

        Returns:
            Tuple of ``(features, scaled_features)`` where ``features`` keeps
            identifiers plus raw feature columns and ``scaled_features`` contains
            only the scaled model inputs aligned with ``FEATURE_COLUMNS``.
        """
        self.logger.info(
            "feature_engineering_started",
            events_rows=len(self.events),
            products_rows=len(self.products),
        )

        pairs = self._build_prediction_pairs()
        features = self._build_features(pairs)
        costumers = Costumer.validate_dataframe(features)
        self.logger.info(
            "features_validated",
            feature_rows=len(features),
            validated_costumers=len(costumers),
        )

        scaled_matrix = self.scaler.transform(features[self.FEATURE_COLUMNS].astype(float))
        scaled_features = pd.DataFrame(
            scaled_matrix,
            columns=self.FEATURE_COLUMNS,
            index=features.index,
        )

        self.logger.info(
            "feature_engineering_completed",
            feature_rows=len(features),
            scaled_rows=len(scaled_features),
        )
        return features, scaled_features

    def _build_prediction_pairs(self) -> pd.DataFrame:
        """Create the cartesian product of known users and all catalog products."""
        users = self.events[["user_id"]].drop_duplicates()
        products = self.products[["product_id"]].drop_duplicates()
        pairs = users.merge(products, how="cross")
        self.logger.info(
            "prediction_pairs_built",
            users=len(users),
            products=len(products),
            pairs=len(pairs),
        )
        return pairs

    def _build_features(self, pairs: pd.DataFrame) -> pd.DataFrame:
        """Derive model features for each user-product pair."""
        interactions = (
            self.events.groupby(["user_id", "product_id"], as_index=False)
            .size()
            .rename(columns={"size": "interactions"})
        )
        product_features = self.products[
            ["product_id", "category", "price", "avg_rating", "popularity_score"]
        ]
        top_affinity = self._compute_user_top_affinity_category()

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

    def _compute_user_top_affinity_category(self) -> pd.DataFrame:
        """Compute each user's top affinity category from historical events."""
        events_with_category = self.events.merge(
            self.products[["product_id", "category"]],
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
