"""Use case that retrieves ranked recommendations for a user."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from recommendations_api.domain.utils.apilogger import ApiLogger


class PredictionsGateway(Protocol):
    """Minimal gateway contract required by the retriever."""

    def get_user_predictions(self, user_id: str) -> pd.DataFrame:
        """Return prediction rows for a user."""

    def get_cold_start_predictions(self, limit: int) -> pd.DataFrame:
        """Return fallback recommendations when the user is unknown."""


class RecommendationsRetriever:
    """Retrieve the top recommendations for a user from DynamoDB.

    The AWS connection/gateway is injected as an attribute so the use case stays
    independent from transport details.
    """

    DEFAULT_LIMIT = 10

    def __init__(self, aws_connector: PredictionsGateway) -> None:
        """Initialize the retriever.

        Args:
            aws_connector: Gateway used to read prediction snapshots.
        """
        self.aws_connector = aws_connector
        self.logger = ApiLogger(self.__class__.__name__)

    def retrieve(
        self,
        user_id: str,
        limit: int | None = None,
    ) -> tuple[pd.DataFrame, bool]:
        """Fetch recommendations for ``user_id``.

        Args:
            user_id: Validated user identifier.
            limit: Optional max number of rows. Defaults to ``DEFAULT_LIMIT``.

        Returns:
            Tuple of ``(recommendations, is_cold_start)``.
        """
        resolved_limit = self.DEFAULT_LIMIT if limit is None else limit
        self.logger.info(
            "recommendations_retrieve_started",
            user_id=user_id,
            limit=resolved_limit,
        )

        predictions = self.aws_connector.get_user_predictions(user_id)
        is_cold_start = predictions.empty
        if is_cold_start:
            self.logger.info("cold_start_fallback_selected", user_id=user_id)
            predictions = self.aws_connector.get_cold_start_predictions(resolved_limit)
        else:
            predictions = (
                predictions.sort_values("recommendation_score", ascending=False)
                .head(resolved_limit)
                .reset_index(drop=True)
            )

        self.logger.info(
            "recommendations_retrieve_completed",
            user_id=user_id,
            rows=len(predictions),
            is_cold_start=is_cold_start,
        )
        return predictions, is_cold_start
