"""Use case that structures recommendation API responses."""

from __future__ import annotations

from typing import Any

import pandas as pd

from recommendations_api.domain.utils.apilogger import ApiLogger


class RecommendationsStructurer:
    """Shape recommendation dataframes into API response payloads."""

    DETAILED_COLUMNS = [
        "user_id",
        "product_id",
        "is_cold_start",
        "interactions",
        "price",
        "avg_rating",
        "popularity_score",
        "user_affinity_match",
        "recommendation_score",
        "category",
    ]

    def __init__(self) -> None:
        """Initialize the structurer."""
        self.logger = ApiLogger(self.__class__.__name__)

    @staticmethod
    def _score_for_row(row: pd.Series, is_cold_start: bool) -> float:
        """Return popularity score for cold start, otherwise model score."""
        if is_cold_start and "popularity_score" in row.index:
            return float(row["popularity_score"])
        return float(row["recommendation_score"])

    def structure_recommendation(
        self,
        user_id: str,
        recommendations: pd.DataFrame,
        is_cold_start: bool,
    ) -> dict[str, Any]:
        """Build the compact response for ``GET /recommendation/{user_id}``.

        Args:
            user_id: Requested user identifier.
            recommendations: Ranked recommendation rows.
            is_cold_start: Whether cold-start fallback was used.

        Returns:
            JSON-serializable response payload including ``cold_start_flag``.
        """
        items = []
        for _, row in recommendations.iterrows():
            if (
                not is_cold_start
                and "user_id" in row.index
                and str(row["user_id"]) != user_id
            ):
                continue
            items.append(
                {
                    "product_id": str(row["product_id"]),
                    "score": self._score_for_row(row, is_cold_start),
                }
            )
        payload = {
            "user_id": user_id,
            "cold_start_flag": is_cold_start,
            "count": len(items),
            "recommendations": items,
        }
        self.logger.info(
            "recommendation_response_structured",
            user_id=user_id,
            count=len(items),
            cold_start_flag=is_cold_start,
            mode="compact",
        )
        return payload

    def structure_filtered(
        self,
        user_id: str,
        recommendations: pd.DataFrame,
        is_cold_start: bool,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the detailed response for ``POST /recommendation_filtered``.

        Returns the full prediction snapshot fields (plus category when available)
        after filters have been applied. On cold start, ``recommendation_score``
        is replaced by ``popularity_score``.

        Args:
            user_id: Requested user identifier.
            recommendations: Filtered recommendation rows.
            is_cold_start: Whether cold-start fallback was used.
            context: Optional request context for observability echo.

        Returns:
            JSON-serializable response payload including ``cold_start_flag``.
        """
        frame = recommendations.copy()
        if is_cold_start and "popularity_score" in frame.columns:
            frame["recommendation_score"] = frame["popularity_score"]
            frame["is_cold_start"] = True

        columns = [
            column
            for column in self.DETAILED_COLUMNS
            if column in frame.columns
        ]
        records = []
        for _, row in frame[columns].iterrows():
            item: dict[str, Any] = {}
            for column in columns:
                value = row[column]
                if column in {
                    "price",
                    "avg_rating",
                    "popularity_score",
                    "recommendation_score",
                }:
                    item[column] = float(value)
                elif column in {"interactions", "user_affinity_match"}:
                    item[column] = int(value)
                elif column == "is_cold_start":
                    item[column] = bool(value)
                else:
                    item[column] = value
            records.append(item)

        payload = {
            "user_id": user_id,
            "cold_start_flag": is_cold_start,
            "count": len(records),
            "context": context or {},
            "recommendations": records,
        }
        self.logger.info(
            "recommendation_response_structured",
            user_id=user_id,
            count=len(records),
            cold_start_flag=is_cold_start,
            mode="detailed",
            context=context or {},
        )
        return payload
