"""
FastAPI application for B-Roll Finder.

Provides REST API access to the B-Roll generation pipeline.

Usage:
    # Development
    uvicorn src.api.main:app --reload

    # Production
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000

    # Or programmatically
    from src.api import create_app
    app = create_app()
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import __version__
from src.api.routes import disambiguation, health, pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: load config, initialize caches, etc.
    yield
    # Shutdown: cleanup resources


def create_app(
    title: str = "B-Roll Finder API",
    debug: bool = False,
    cors_origins: Optional[list[str]] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        title: API title for OpenAPI docs
        debug: Enable debug mode
        cors_origins: List of allowed CORS origins (default: ["*"])

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        summary="Automated B-Roll generation from video transcripts",
        description="""
## Overview

REST API for the B-Roll Finder pipeline. Automatically extract entities from
video transcripts, find relevant Wikipedia images, and generate NLE-compatible
XML timelines.

## Features

- **Entity Extraction**: Parse SRT files to identify people, places, events
- **Wikipedia Integration**: Search and download relevant images with disambiguation
- **Timeline Generation**: Export DaVinci Resolve-compatible XML

## Workflow

1. **Start Pipeline**: `POST /api/v1/pipeline/start` with your SRT file
2. **Monitor Progress**: `GET /api/v1/pipeline/{id}` for status updates
3. **Get Results**: `GET /api/v1/pipeline/{id}/result` when complete

## Authentication

Currently no authentication required. API keys for Wikipedia and LLM services
are configured server-side.
        """,
        version=__version__,
        debug=debug,
        lifespan=lifespan,
        openapi_tags=[
            {
                "name": "Health",
                "description": "Service health and discovery endpoints",
            },
            {
                "name": "Pipeline",
                "description": "Full B-Roll generation pipeline operations",
            },
            {
                "name": "Disambiguation",
                "description": "Wikipedia entity search and disambiguation",
            },
        ],
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
        contact={
            "name": "B-Roll Finder",
            "url": "https://github.com/yourusername/b-roll-finder-app",
        },
    )

    # CORS configuration
    if cors_origins is None:
        cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(disambiguation.router, prefix="/api/v1", tags=["Disambiguation"])
    app.include_router(pipeline.router, prefix="/api/v1", tags=["Pipeline"])

    return app


# Default app instance for uvicorn
app = create_app()
