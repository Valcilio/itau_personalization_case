"""Unit tests for recommendations_api.domain.entities.user."""

import pytest

from recommendations_api.domain.entities.user import User


def test_validate_user_id_accepts_valid_pattern() -> None:
    user = User.validate_user_id("u_0231")
    assert user.user_id == "u_0231"


def test_validate_user_id_rejects_invalid_pattern() -> None:
    with pytest.raises(ValueError):
        User.validate_user_id("invalid")


def test_validate_filtered_request_parses_payload() -> None:
    filters = User.validate_filtered_request(
        {
            "user_id": "u_0231",
            "limit": 5,
            "exclude_product_ids": ["p_001"],
            "categories": ["livros"],
            "min_price": 5,
            "max_price": 40,
            "context": {"device": "mobile"},
        }
    )
    assert filters.limit == 5
    assert filters.exclude_product_ids == ["p_001"]


def test_validate_filtered_request_rejects_invalid_price_range() -> None:
    with pytest.raises(ValueError, match="min_price"):
        User.validate_filtered_request(
            {"user_id": "u_0231", "min_price": 50, "max_price": 10}
        )


def test_validate_string_list_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="exclude_product_ids"):
        User.validate_filtered_request(
            {"user_id": "u_0231", "exclude_product_ids": "p_001"}
        )


def test_optional_float_rejects_boolean() -> None:
    with pytest.raises(ValueError, match="min_price"):
        User.validate_filtered_request({"user_id": "u_0231", "min_price": True})
