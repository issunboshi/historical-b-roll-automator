"""
FastAPI application for B-Roll Finder.

Provides REST API access to the pipeline and individual tools.
"""

from src.api.main import create_app

__all__ = ["create_app"]
