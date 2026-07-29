"""In-process metrics collector for the recommendations API."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class MetricsCollector:
    """Collect basic request metrics exposed by ``GET /metrics``."""

    request_count: int = 0
    error_count: int = 0
    cold_start_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(
        self,
        *,
        latency_ms: float,
        is_error: bool = False,
        is_cold_start: bool = False,
    ) -> None:
        """Record one completed request."""
        with self._lock:
            self.request_count += 1
            if is_error:
                self.error_count += 1
            if is_cold_start:
                self.cold_start_count += 1
            self.latencies_ms.append(latency_ms)
            if len(self.latencies_ms) > 5000:
                self.latencies_ms = self.latencies_ms[-5000:]

    def percentile(self, pct: float) -> float:
        """Return a latency percentile in milliseconds."""
        with self._lock:
            if not self.latencies_ms:
                return 0.0
            ordered = sorted(self.latencies_ms)
            index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
            return float(ordered[index])

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        with self._lock:
            request_count = self.request_count
            error_count = self.error_count
            cold_start_count = self.cold_start_count
            latencies = list(self.latencies_ms)

        p50 = self.percentile(50)
        p95 = self.percentile(95)
        avg = (sum(latencies) / len(latencies)) if latencies else 0.0
        lines = [
            "# HELP recommendations_api_requests_total Total HTTP requests handled.",
            "# TYPE recommendations_api_requests_total counter",
            f"recommendations_api_requests_total {request_count}",
            "# HELP recommendations_api_errors_total Total HTTP errors.",
            "# TYPE recommendations_api_errors_total counter",
            f"recommendations_api_errors_total {error_count}",
            "# HELP recommendations_api_cold_start_total Total cold-start fallbacks.",
            "# TYPE recommendations_api_cold_start_total counter",
            f"recommendations_api_cold_start_total {cold_start_count}",
            "# HELP recommendations_api_latency_ms Request latency in milliseconds.",
            "# TYPE recommendations_api_latency_ms summary",
            f'recommendations_api_latency_ms{{quantile="0.5"}} {p50}',
            f'recommendations_api_latency_ms{{quantile="0.95"}} {p95}',
            f"recommendations_api_latency_ms_sum {sum(latencies) if latencies else 0.0}",
            f"recommendations_api_latency_ms_count {len(latencies)}",
            "# HELP recommendations_api_latency_avg_ms Average request latency.",
            "# TYPE recommendations_api_latency_avg_ms gauge",
            f"recommendations_api_latency_avg_ms {avg}",
        ]
        return "\n".join(lines) + "\n"


class Timer:
    """Simple wall-clock timer used by the HTTP layer."""

    def __init__(self) -> None:
        self._started = time.perf_counter()

    def elapsed_ms(self) -> float:
        """Return elapsed milliseconds since construction."""
        return (time.perf_counter() - self._started) * 1000.0
