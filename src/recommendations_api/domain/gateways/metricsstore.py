"""In-memory storage for recommendations API metrics."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

MAX_LATENCY_OBSERVATIONS = 5000


@dataclass(frozen=True)
class MetricsSnapshot:
    """Aggregated metrics loaded from the in-memory store."""

    requests_total: int
    errors_total: int
    cold_start_total: int
    latencies_ms: tuple[float, ...]

    @property
    def latency_count(self) -> int:
        return len(self.latencies_ms)

    @property
    def latency_sum(self) -> float:
        return float(sum(self.latencies_ms))

    @property
    def latency_avg(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return self.latency_sum / self.latency_count

    def latency_quantile(self, pct: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        if len(ordered) == 1:
            return float(ordered[0])
        rank = (pct / 100) * (len(ordered) - 1)
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        weight = rank - lower
        return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


class MetricsStore(Protocol):
    """Contract for recording and loading API metrics."""

    def record_request(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        """Persist one completed recommendation request."""

    def load_snapshot(self) -> MetricsSnapshot:
        """Load the current aggregated metrics snapshot."""


class InMemoryMetricsStore:
    """In-memory metrics store used by the API and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests_total = 0
        self._errors_total = 0
        self._cold_start_total = 0
        self._latencies_ms: list[float] = []

    def record_request(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        with self._lock:
            self._requests_total += 1
            if is_error:
                self._errors_total += 1
            if is_cold_start:
                self._cold_start_total += 1
            self._latencies_ms.append(latency_ms)
            if len(self._latencies_ms) > MAX_LATENCY_OBSERVATIONS:
                self._latencies_ms = self._latencies_ms[-MAX_LATENCY_OBSERVATIONS:]

    def load_snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                requests_total=self._requests_total,
                errors_total=self._errors_total,
                cold_start_total=self._cold_start_total,
                latencies_ms=tuple(self._latencies_ms),
            )


def build_metrics_store(store: MetricsStore | None = None) -> MetricsStore:
    """Return an explicit store or the default in-memory implementation."""
    if store is not None:
        return store
    return InMemoryMetricsStore()
