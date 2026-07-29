"""Structured logging utilities for the recommendations API."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import boto3

try:
    import watchtower
except ImportError:  # pragma: no cover - optional dependency guard
    watchtower = None


class ApiLogger:
    """Configure and emit structured logs for the recommendations API.

    Each component receives its own logger namespace under
    ``recommendations_api.<component>``.
    """

    LOG_NAMESPACE = "recommendations_api"
    _configured = False

    def __init__(self, component: str) -> None:
        """Create a logger bound to an API component.

        Args:
            component: Logical owner of the log messages, typically the class name.
        """
        self.component = component
        self._logger = logging.getLogger(f"{self.LOG_NAMESPACE}.{component}")

    @classmethod
    def configure(cls, level: int | None = None) -> None:
        """Configure stream and optional CloudWatch handlers."""
        if cls._configured:
            return

        resolved_level = level or getattr(
            logging,
            os.getenv("LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        )
        formatter = logging.Formatter("%(message)s")

        logger = logging.getLogger(cls.LOG_NAMESPACE)
        logger.setLevel(resolved_level)
        logger.propagate = False
        logger.handlers.clear()

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(resolved_level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        cloudwatch_handler = cls._build_cloudwatch_handler(resolved_level, formatter)
        if cloudwatch_handler is not None:
            logger.addHandler(cloudwatch_handler)

        cls._configured = True
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": logging.getLevelName(resolved_level),
                    "component": cls.LOG_NAMESPACE,
                    "event": "logging_configured",
                    "handlers": [
                        handler.__class__.__name__ for handler in logger.handlers
                    ],
                },
                ensure_ascii=False,
            )
        )

    @classmethod
    def _build_cloudwatch_handler(
        cls,
        level: int,
        formatter: logging.Formatter,
    ) -> logging.Handler | None:
        """Build the CloudWatch handler when configured and not running on ECS."""
        log_group = os.getenv("CLOUDWATCH_LOG_GROUP", "").strip()
        if not log_group or cls._running_on_ecs():
            return None
        if watchtower is None:
            raise ImportError(
                "watchtower is required when CLOUDWATCH_LOG_GROUP is configured"
            )

        region_name = os.getenv("AWS_REGION", "us-east-1")
        stream_name = os.getenv(
            "CLOUDWATCH_LOG_STREAM",
            f"recommendations-api-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        )
        logs_client = boto3.client("logs", region_name=region_name)
        cloudwatch_handler = watchtower.CloudWatchLogHandler(
            log_group=log_group,
            stream_name=stream_name,
            boto3_client=logs_client,
            create_log_group=False,
        )
        cloudwatch_handler.setLevel(level)
        cloudwatch_handler.setFormatter(formatter)
        return cloudwatch_handler

    @staticmethod
    def _running_on_ecs() -> bool:
        """Return True when the process is running inside an ECS task."""
        return bool(
            os.getenv("ECS_CONTAINER_METADATA_URI_V4")
            or os.getenv("ECS_CONTAINER_METADATA_URI")
        )

    def debug(self, event: str, **fields: Any) -> None:
        """Emit a debug-level structured log."""
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        """Emit an info-level structured log."""
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        """Emit a warning-level structured log."""
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        """Emit an error-level structured log."""
        self._log(logging.ERROR, event, **fields)

    def exception(self, event: str, **fields: Any) -> None:
        """Emit an exception log including the current traceback."""
        self._log(logging.ERROR, event, exc_info=True, **fields)

    def _log(self, level: int, event: str, exc_info: bool = False, **fields: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": logging.getLevelName(level),
            "component": self.component,
            "event": event,
            **fields,
        }
        self._logger.log(level, json.dumps(payload, ensure_ascii=False), exc_info=exc_info)
