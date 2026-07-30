"""FastAPI entrypoint for the recommendations API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from recommendations_api.domain.gateways.recommendationshandler import (
    RecommendationsHandler,
)
from recommendations_api.domain.utils.apilogger import ApiLogger
from recommendations_api.domain.utils.metrics import (
    MetricsCollector,
    Timer,
    create_metrics_collector,
)

ApiLogger.configure()
logger = ApiLogger("main")


class _MetricsHolder:
    """Mutable holder used to swap the metrics collector in tests without globals."""

    instance: MetricsCollector = create_metrics_collector()


def get_metrics_collector() -> MetricsCollector:
    """Return the process-wide metrics collector."""
    return _MetricsHolder.instance


def set_metrics_collector(collector: MetricsCollector) -> None:
    """Override the process-wide metrics collector (used by tests)."""
    _MetricsHolder.instance = collector


class _HandlerHolder:
    """Mutable holder used to swap the handler in tests without globals."""

    instance: RecommendationsHandler | None = None


app = FastAPI(
    title="Recommendations API",
    version="1.0.0",
    description=(
        "Serving purchase-propensity recommendations from the DynamoDB "
        "predictions table. Public access is enforced by API Gateway API keys."
    ),
)


def get_handler() -> RecommendationsHandler:
    """Return a process-wide handler instance, creating it on first use."""
    if _HandlerHolder.instance is None:
        _HandlerHolder.instance = RecommendationsHandler()
    return _HandlerHolder.instance


def set_handler(handler: RecommendationsHandler) -> None:
    """Override the process-wide handler (used by tests)."""
    _HandlerHolder.instance = handler


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness payload."""
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics(
    metrics_format: str = Query(
        default="prometheus",
        alias="format",
        description=(
            "Output format: prometheus (default), datadog (Metrics API v2 series), "
            "or both (JSON with prometheus text + datadog series)."
        ),
    ),
) -> Response:
    """Expose Prometheus and Datadog-formatted metrics."""
    collector = get_metrics_collector()
    collector.log_snapshot(source="metrics_endpoint")

    normalized = metrics_format.strip().lower()
    if normalized == "datadog":
        return JSONResponse(content=collector.render_datadog())
    if normalized == "both":
        return JSONResponse(content=collector.render_combined())
    if normalized != "prometheus":
        raise HTTPException(
            status_code=400,
            detail="format must be one of: prometheus, datadog, both",
        )

    return PlainTextResponse(
        content=collector.render_prometheus(),
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
        get_metrics_collector().observe(
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
            category=payload.get("category"),
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
        get_metrics_collector().observe(
            latency_ms=timer.elapsed_ms(),
            is_error=is_error,
            is_cold_start=is_cold_start,
        )
