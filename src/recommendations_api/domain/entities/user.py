"""Domain entity used to validate recommendation API requests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


USER_ID_PATTERN = re.compile(r"^u_\d{4}$")
PRODUCT_ID_PATTERN = re.compile(r"^p_\d{3}$")
ALLOWED_CATEGORIES = {
    "beleza",
    "casa",
    "eletronicos",
    "esporte",
    "livros",
    "moda",
}


@dataclass(frozen=True)
class RecommendationFilters:
    """Validated filter payload for ``POST /recommendation_filtered``."""

    user_id: str
    limit: int | None = None
    exclude_product_ids: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    exclude_categories: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    min_avg_rating: float | None = None
    min_popularity_score: float | None = None
    min_recommendation_score: float | None = None
    only_affinity_match: bool = False
    exclude_cold_start: bool = False


@dataclass(frozen=True)
class User:
    """Validate user identifiers and filtered recommendation requests."""

    user_id: str

    @classmethod
    def validate_user_id(cls, user_id: str) -> "User":
        """Validate a user identifier against the ``u_XXXX`` pattern.

        Args:
            user_id: Raw user identifier from the request path or body.

        Returns:
            Validated ``User`` entity.

        Raises:
            ValueError: If the identifier does not match the expected pattern.
        """
        if not isinstance(user_id, str) or not USER_ID_PATTERN.match(user_id):
            raise ValueError(
                "user_id must match the pattern u_XXXX (example: u_0231)"
            )
        return cls(user_id=user_id)

    @classmethod
    def validate_filtered_request(cls, payload: dict[str, Any]) -> RecommendationFilters:
        """Validate the POST body for ``/recommendation_filtered``.

        Args:
            payload: Raw JSON body from the HTTP request.

        Returns:
            Validated filter object.

        Raises:
            ValueError: If any field violates the expected contract.
        """
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        user = cls.validate_user_id(str(payload.get("user_id", "")))
        limit = payload.get("limit")
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise ValueError("limit must be an integer greater than 0")

        exclude_product_ids = cls._validate_string_list(
            payload.get("exclude_product_ids", []),
            field_name="exclude_product_ids",
            item_pattern=PRODUCT_ID_PATTERN,
        )
        categories = cls._validate_string_list(
            payload.get("categories", []),
            field_name="categories",
        )
        exclude_categories = cls._validate_string_list(
            payload.get("exclude_categories", []),
            field_name="exclude_categories",
        )
        for category in [*categories, *exclude_categories]:
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(
                    f"unsupported category '{category}'. "
                    f"allowed={sorted(ALLOWED_CATEGORIES)}"
                )

        context = payload.get("context", {})
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise ValueError("context must be an object")

        min_price = cls._optional_float(payload.get("min_price"), "min_price")
        max_price = cls._optional_float(payload.get("max_price"), "max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("min_price must be <= max_price")

        min_avg_rating = cls._optional_float(
            payload.get("min_avg_rating"),
            "min_avg_rating",
            minimum=0.0,
            maximum=5.0,
        )
        min_popularity_score = cls._optional_float(
            payload.get("min_popularity_score"),
            "min_popularity_score",
            minimum=0.0,
            maximum=1.0,
        )
        min_recommendation_score = cls._optional_float(
            payload.get("min_recommendation_score"),
            "min_recommendation_score",
            minimum=0.0,
            maximum=1.0,
        )

        only_affinity_match = bool(payload.get("only_affinity_match", False))
        exclude_cold_start = bool(payload.get("exclude_cold_start", False))

        return RecommendationFilters(
            user_id=user.user_id,
            limit=limit,
            exclude_product_ids=exclude_product_ids,
            context=context,
            categories=categories,
            exclude_categories=exclude_categories,
            min_price=min_price,
            max_price=max_price,
            min_avg_rating=min_avg_rating,
            min_popularity_score=min_popularity_score,
            min_recommendation_score=min_recommendation_score,
            only_affinity_match=only_affinity_match,
            exclude_cold_start=exclude_cold_start,
        )

    @staticmethod
    def _validate_string_list(
        value: Any,
        field_name: str,
        item_pattern: re.Pattern[str] | None = None,
    ) -> list[str]:
        """Validate a list of strings, optionally matching a regex pattern."""
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{field_name} must be a list of strings")
        if item_pattern is not None:
            invalid = [item for item in value if not item_pattern.match(item)]
            if invalid:
                raise ValueError(f"{field_name} contains invalid ids: {invalid}")
        return list(value)

    @staticmethod
    def _optional_float(
        value: Any,
        field_name: str,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        """Validate an optional numeric field."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} must be a number")
        number = float(value)
        if minimum is not None and number < minimum:
            raise ValueError(f"{field_name} must be >= {minimum}")
        if maximum is not None and number > maximum:
            raise ValueError(f"{field_name} must be <= {maximum}")
        return number
