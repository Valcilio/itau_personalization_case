"""Shared pytest fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

# Integration tests call live AWS and can take several minutes.
# Run them explicitly with: pytest tests/integration -m integration
collect_ignore = ["integration"]


@pytest.fixture
def sample_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": ["u_1", "u_1", "u_2"],
            "product_id": ["p_1", "p_1", "p_2"],
            "event_type": ["view", "purchase", "click"],
        }
    )


@pytest.fixture
def sample_products() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": ["p_1", "p_2"],
            "category": ["livros", "esporte"],
            "price": [10.0, 20.0],
            "avg_rating": [4.0, 3.5],
            "popularity_score": [0.8, 0.2],
        }
    )
