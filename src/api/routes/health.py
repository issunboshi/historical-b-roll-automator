"""
Health check endpoints.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from src import __version__

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    timestamp: str
    environment: dict


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    checks: dict


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic health check endpoint.

    Returns application status, version, and environment info.
    """
    return HealthResponse(
        status="healthy",
        version=__version__,
        timestamp=datetime.utcnow().isoformat() + "Z",
        environment={
            "python_version": os.sys.version.split()[0],
            "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
            "wikipedia_token_set": bool(os.environ.get("WIKIPEDIA_API_ACCESS_TOKEN")),
        },
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    """Readiness check for orchestration systems.

    Verifies that required dependencies and credentials are available.
    """
    checks = {
        "anthropic_api": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai_api": bool(os.environ.get("OPENAI_API_KEY")),
    }

    # Ready if at least one LLM provider is configured
    ready = checks["anthropic_api"] or checks["openai_api"]

    return ReadinessResponse(ready=ready, checks=checks)
