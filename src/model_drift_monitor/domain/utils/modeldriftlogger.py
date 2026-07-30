"""Structured logging utilities for the model drift monitor pipeline."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import boto3

try:
    import watchtower
except ImportError:  # pragma: no cover
    watchtower = None


class ModelDriftLogger:
    """Configure and emit structured logs for the drift monitor batch job."""

    LOG_NAMESPACE = "model_drift_monitor"
    _configured = False

    def __init__(self, component: str) -> None:
        self.component = component
        self._logger = logging.getLogger(f"{self.LOG_NAMESPACE}.{component}")

    @classmethod
    def configure(cls, level: int | None = None) -> None:
        """Configure stream logging for the drift monitor process."""
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

    @classmethod
    def _build_cloudwatch_handler(
        cls,
        level: int,
        formatter: logging.Formatter,
    ) -> logging.Handler | None:
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
            f"model-drift-monitor-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
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
        return bool(
            os.getenv("ECS_CONTAINER_METADATA_URI_V4")
            or os.getenv("ECS_CONTAINER_METADATA_URI")
        )

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)

    def exception(self, event: str, **fields: Any) -> None:
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
