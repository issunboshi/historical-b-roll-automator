"""
B-Roll Finder - Core library for extracting entities and downloading Wikipedia images.

This package provides both CLI and API access to the B-Roll generation pipeline.

Usage:
    # CLI
    python broll.py pipeline --srt video.srt --output-dir ./output

    # API
    from src.api import create_app
    app = create_app()

    # Core library
    from src.core.disambiguation import disambiguate_search_results
    from src.models.entity import Entity, Occurrence
"""

__version__ = "0.2.0"
