"""API Gateway HTTP API Lambda authorizer for x-api-key validation."""

from __future__ import annotations

import os


def handler(event, _context):
    """Authorize requests using the API Gateway-managed API key."""
    headers = event.get("headers") or {}
    provided = headers.get("x-api-key") or headers.get("X-Api-Key") or ""
    expected = os.environ.get("API_KEY", "")

    if expected and provided == expected:
        return {"isAuthorized": True}

    return {"isAuthorized": False}
