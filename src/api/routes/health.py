"""
Health and info endpoints for service discovery.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src import __version__

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Service status")
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")


class DetailedHealthResponse(BaseModel):
    """Detailed health check response with environment info."""

    status: str = "healthy"
    version: str
    timestamp: str
    environment: dict


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    checks: dict


class EndpointInfo(BaseModel):
    """Information about an API endpoint."""

    path: str
    method: str
    description: str


class ServiceInfo(BaseModel):
    """Service metadata for discovery."""

    name: str = Field(description="Service name")
    version: str = Field(description="Service version")
    description: str = Field(description="Service description")
    api_prefix: str = Field(description="API prefix for routing")
    port: int = Field(description="Default port")
    endpoints: list[EndpointInfo] = Field(description="Available endpoints")


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint for load balancers and orchestration."""
    return HealthResponse(
        status="ok",
        service="b-roll-finder",
        version=__version__,
    )


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check() -> DetailedHealthResponse:
    """Detailed health check with environment info.

    Returns application status, version, and environment info.
    """
    return DetailedHealthResponse(
        status="ok",
        version=__version__,
        timestamp=datetime.now(UTC).isoformat(),
        environment={
            "python_version": sys.version.split()[0],
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


@router.get("/info", response_model=ServiceInfo)
async def service_info() -> ServiceInfo:
    """Service metadata for discovery and documentation."""
    return ServiceInfo(
        name="b-roll-finder",
        version=__version__,
        description="Extract entities from transcripts, download Wikipedia images, generate NLE timelines",
        api_prefix="/api/broll",
        port=8001,
        endpoints=[
            EndpointInfo(
                path="/api/v1/pipeline/start",
                method="POST",
                description="Start a new pipeline run",
            ),
            EndpointInfo(
                path="/api/v1/pipeline/{id}",
                method="GET",
                description="Get pipeline status",
            ),
            EndpointInfo(
                path="/api/v1/pipeline/{id}/result",
                method="GET",
                description="Get pipeline result",
            ),
            EndpointInfo(
                path="/api/v1/disambiguate",
                method="POST",
                description="Disambiguate a single entity",
            ),
            EndpointInfo(
                path="/api/v1/search-candidates",
                method="POST",
                description="Search Wikipedia candidates",
            ),
        ],
    )
