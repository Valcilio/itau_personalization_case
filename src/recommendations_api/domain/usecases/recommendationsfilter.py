"""Use case that applies recommendation filters."""

from __future__ import annotations

import pandas as pd

from recommendations_api.domain.entities.user import RecommendationFilters
from recommendations_api.domain.utils.apilogger import ApiLogger


class RecommendationsFilter:
    """Filter a recommendation dataframe according to the POST contract."""

    def __init__(self) -> None:
        """Initialize the filter use case."""
        self.logger = ApiLogger(self.__class__.__name__)

    def apply(
        self,
        recommendations: pd.DataFrame,
        filters: RecommendationFilters,
    ) -> pd.DataFrame:
        """Apply all configured filters and re-rank by model score.

        Args:
            recommendations: Candidate recommendation rows for a user.
            filters: Validated filter payload.

        Returns:
            Filtered and re-ranked dataframe.
        """
        filtered = recommendations.copy()
        initial_rows = len(filtered)

        if filters.exclude_product_ids and not filtered.empty:
            filtered = filtered[
                ~filtered["product_id"].isin(filters.exclude_product_ids)
            ]

        if filters.categories and "category" in filtered.columns and not filtered.empty:
            filtered = filtered[filtered["category"].isin(filters.categories)]

        if (
            filters.exclude_categories
            and "category" in filtered.columns
            and not filtered.empty
        ):
            filtered = filtered[~filtered["category"].isin(filters.exclude_categories)]

        if filters.min_price is not None and not filtered.empty:
            filtered = filtered[filtered["price"] >= filters.min_price]
        if filters.max_price is not None and not filtered.empty:
            filtered = filtered[filtered["price"] <= filters.max_price]

        if filters.min_avg_rating is not None and not filtered.empty:
            filtered = filtered[filtered["avg_rating"] >= filters.min_avg_rating]

        if filters.min_popularity_score is not None and not filtered.empty:
            filtered = filtered[
                filtered["popularity_score"] >= filters.min_popularity_score
            ]

        if filters.min_recommendation_score is not None and not filtered.empty:
            filtered = filtered[
                filtered["recommendation_score"] >= filters.min_recommendation_score
            ]

        if filters.only_affinity_match and not filtered.empty:
            filtered = filtered[filtered["user_affinity_match"] == 1]

        if filters.exclude_cold_start and not filtered.empty:
            filtered = filtered[~filtered["is_cold_start"].astype(bool)]

        filtered = (
            filtered.sort_values("recommendation_score", ascending=False)
            .reset_index(drop=True)
        )
        if filters.limit is not None:
            filtered = filtered.head(filters.limit).reset_index(drop=True)

        self.logger.info(
            "recommendations_filtered",
            user_id=filters.user_id,
            initial_rows=initial_rows,
            filtered_rows=len(filtered),
            limit=filters.limit,
            context=filters.context,
        )
        return filtered
