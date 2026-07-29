"""FastAPI entrypoint for the recommendations API."""

from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from recommendations_api.domain.gateways.recommendationshandler import (
    RecommendationsHandler,
)
from recommendations_api.domain.utils.apilogger import ApiLogger
from recommendations_api.domain.utils.metrics import MetricsCollector, Timer

ApiLogger.configure()
logger = ApiLogger("main")
metrics = MetricsCollector()
_handler: RecommendationsHandler | None = None

PUBLIC_PATHS = {"/health"}

app = FastAPI(
    title="Recommendations API",
    version="1.0.0",
    description=(
        "Serving purchase-propensity recommendations from the DynamoDB "
        "predictions table. Protected by x-api-key."
    ),
)


def get_handler() -> RecommendationsHandler:
    """Return a process-wide handler instance, creating it on first use."""
    global _handler  # noqa: PLW0603
    if _handler is None:
        _handler = RecommendationsHandler()
    return _handler


def set_handler(handler: RecommendationsHandler) -> None:
    """Override the process-wide handler (used by tests)."""
    global _handler  # noqa: PLW0603
    _handler = handler


def _expected_api_key() -> str:
    """Return the API key configured for request authentication."""
    return os.getenv("RECOMMENDATIONS_API_KEY", "").strip()


@app.middleware("http")
async def require_api_key(request: Request, call_next: Callable):
    """Require ``x-api-key`` for all routes except health checks.

    The service is intentionally reachable from the public internet through API
    Gateway with no IP allowlist. Authentication is enforced via API key.
    """
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    expected = _expected_api_key()
    if not expected:
        logger.error("api_key_not_configured")
        return JSONResponse(
            status_code=503,
            content={"detail": "RECOMMENDATIONS_API_KEY is not configured"},
        )

    provided = request.headers.get("x-api-key", "").strip()
    if provided != expected:
        logger.warning(
            "api_key_rejected",
            path=request.url.path,
            has_header=bool(provided),
        )
        return JSONResponse(status_code=401, content={"detail": "invalid api key"})

    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness payload."""
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics() -> Response:
    """Expose basic Prometheus metrics."""
    return PlainTextResponse(
        content=metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


@app.get("/recommendation/{user_id}")
@app.get("/recommendations/{user_id}")
def get_recommendation(user_id: str) -> dict[str, Any]:
    """Return top recommendations for a user from DynamoDB predictions."""
    timer = Timer()
    is_error = False
    is_cold_start = False
    try:
        payload = get_handler().get_recommendation(user_id)
        is_cold_start = bool(payload.get("cold_start_flag"))
        logger.info(
            "recommendation_request_completed",
            user_id=user_id,
            latency_ms=round(timer.elapsed_ms(), 2),
            cold_start_flag=is_cold_start,
            count=payload.get("count"),
            source="dynamodb_predictions",
        )
        return payload
    except ValueError as error:
        is_error = True
        logger.warning(
            "recommendation_request_rejected",
            user_id=user_id,
            reason=str(error),
            latency_ms=round(timer.elapsed_ms(), 2),
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # pylint: disable=broad-exception-caught
        is_error = True
        logger.exception(
            "recommendation_request_failed",
            user_id=user_id,
            latency_ms=round(timer.elapsed_ms(), 2),
        )
        raise HTTPException(status_code=500, detail="internal server error") from error
    finally:
        metrics.observe(
            latency_ms=timer.elapsed_ms(),
            is_error=is_error,
            is_cold_start=is_cold_start,
        )


@app.post("/recommendation_filtered")
@app.post("/recommendations_filtered")
async def post_recommendation_filtered(request: Request) -> dict[str, Any]:
    """Return filtered recommendations for a user from DynamoDB predictions."""
    timer = Timer()
    is_error = False
    is_cold_start = False
    user_id = ""
    try:
        payload = await request.json()
        user_id = str(payload.get("user_id", ""))
        response = get_handler().get_filtered_recommendations(payload)
        is_cold_start = bool(response.get("cold_start_flag"))
        logger.info(
            "filtered_recommendation_request_completed",
            user_id=user_id,
            latency_ms=round(timer.elapsed_ms(), 2),
            cold_start_flag=is_cold_start,
            count=response.get("count"),
            context=payload.get("context", {}),
            source="dynamodb_predictions",
        )
        return response
    except ValueError as error:
        is_error = True
        logger.warning(
            "filtered_recommendation_request_rejected",
            user_id=user_id,
            reason=str(error),
            latency_ms=round(timer.elapsed_ms(), 2),
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # pylint: disable=broad-exception-caught
        is_error = True
        logger.exception(
            "filtered_recommendation_request_failed",
            user_id=user_id,
            latency_ms=round(timer.elapsed_ms(), 2),
        )
        raise HTTPException(status_code=500, detail="internal server error") from error
    finally:
        metrics.observe(
            latency_ms=timer.elapsed_ms(),
            is_error=is_error,
            is_cold_start=is_cold_start,
        )
