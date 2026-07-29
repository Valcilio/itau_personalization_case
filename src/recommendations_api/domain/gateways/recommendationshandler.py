"""Gateway that orchestrates recommendation retrieval and filtering."""

from __future__ import annotations

from typing import Any

from recommendations_api.domain.entities.user import RecommendationFilters, User
from recommendations_api.domain.gateways.awsconnector import AwsConnector
from recommendations_api.domain.usecases.recommendationsfilter import RecommendationsFilter
from recommendations_api.domain.usecases.recommendationsretriever import (
    RecommendationsRetriever,
)
from recommendations_api.domain.usecases.recommendationsstructurer import (
    RecommendationsStructurer,
)
from recommendations_api.domain.utils.apilogger import ApiLogger


class RecommendationsHandler:
    """Orchestrate recommendation use cases for the HTTP layer."""

    def __init__(
        self,
        aws_connector: Any | None = None,
        retriever: RecommendationsRetriever | None = None,
        filter_use_case: RecommendationsFilter | None = None,
        structurer: RecommendationsStructurer | None = None,
    ) -> None:
        """Initialize handler dependencies.

        Args:
            aws_connector: AWS gateway. Created automatically when omitted.
            retriever: Optional retriever override for tests.
            filter_use_case: Optional filter override for tests.
            structurer: Optional structurer override for tests.
        """
        self.aws_connector = aws_connector or AwsConnector()
        self.retriever = retriever or RecommendationsRetriever(self.aws_connector)
        self.filter_use_case = filter_use_case or RecommendationsFilter()
        self.structurer = structurer or RecommendationsStructurer()
        self.logger = ApiLogger(self.__class__.__name__)

    def get_recommendation(self, user_id: str) -> dict[str, Any]:
        """Handle ``GET /recommendation/{user_id}``.

        Args:
            user_id: Raw user identifier from the path.

        Returns:
            Compact recommendation payload.
        """
        user = User.validate_user_id(user_id)
        recommendations, is_cold_start = self.retriever.retrieve(user.user_id)
        return self.structurer.structure_recommendation(
            user_id=user.user_id,
            recommendations=recommendations,
            is_cold_start=is_cold_start,
        )

    def get_filtered_recommendations(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle ``POST /recommendation_filtered``.

        Args:
            payload: Raw JSON body.

        Returns:
            Detailed filtered recommendation payload.
        """
        filters: RecommendationFilters = User.validate_filtered_request(payload)
        self.logger.info(
            "filtered_recommendation_started",
            user_id=filters.user_id,
            context=filters.context,
        )

        predictions = self.aws_connector.get_user_predictions(filters.user_id)
        is_cold_start = predictions.empty
        if is_cold_start:
            fallback_limit = filters.limit or RecommendationsRetriever.DEFAULT_LIMIT
            predictions = self.aws_connector.get_cold_start_predictions(fallback_limit)

        filtered = self.filter_use_case.apply(predictions, filters)
        if filters.limit is None:
            filtered = filtered.head(RecommendationsRetriever.DEFAULT_LIMIT).reset_index(
                drop=True
            )

        return self.structurer.structure_filtered(
            user_id=filters.user_id,
            recommendations=filtered,
            is_cold_start=is_cold_start,
            context=filters.context,
        )
