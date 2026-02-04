#!/usr/bin/env python3
"""
disambiguation.py

Wikipedia disambiguation module for B-roll automation.

NOTE: API keys are auto-loaded from .wikipedia_image_downloader.ini via config module.

This is a CLI wrapper around the core disambiguation module in src/core/disambiguation.py.
All business logic has been moved to the core module for reuse by CLI, API, and other tools.

Usage:
    python tools/disambiguation.py --query "Michael Jordan" --context "basketball player" --video-topic "NBA History"

For programmatic use, import from src.core or src.models:
    from src.core.disambiguation import (
        disambiguate_search_results,
        search_wikipedia_candidates,
    )
    from src.models.disambiguation import (
        DisambiguationDecision,
        CandidateInfo,
    )
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

import requests
from anthropic import Anthropic
from diskcache import Cache

# Import core business logic and models from src/
# These imports are the canonical location for all disambiguation logic
from src.core.disambiguation import (
    WIKIPEDIA_API,
    USER_AGENT,
    derive_match_quality,
    apply_confidence_routing,
    log_disambiguation_decision,
    process_disambiguation_result,
    search_wikipedia_candidates,
    is_disambiguation_page,
    extract_disambiguation_links,
    fetch_candidate_info,
    disambiguate_entity,
    resolve_disambiguation,
    disambiguate_search_results,
)
from src.core.review import (
    write_review_file,
    load_overrides,
    get_override,
    create_override_entry,
)
from src.models.disambiguation import (
    CandidateInfo,
    DisambiguationDecision,
    DisambiguationReviewEntry,
)


# =============================================================================
# CLI Interface
# =============================================================================


def main(argv: List[str] = None) -> int:
    """CLI entry point for disambiguation testing.

    Usage:
        python tools/disambiguation.py --query "Michael Jordan" --context "basketball player" --video-topic "NBA History"

    Returns:
        0 on success, 1 on error, 2 on missing API key
    """
    parser = argparse.ArgumentParser(
        description="Test Wikipedia disambiguation for an entity"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Entity name to disambiguate"
    )
    parser.add_argument(
        "--context",
        default="",
        help="Transcript context where entity appears"
    )
    parser.add_argument(
        "--video-topic",
        default="Unknown video",
        help="Video topic for disambiguation"
    )
    parser.add_argument(
        "--cache-dir",
        default="/tmp/wikipedia_cache",
        help="Cache directory (default: /tmp/wikipedia_cache)"
    )
    parser.add_argument(
        "--entity-type",
        default="concepts",
        help="Entity type (people, events, places, organizations, concepts)"
    )

    args = parser.parse_args(argv)

    # Create session and cache
    session = requests.Session()
    cache = Cache(args.cache_dir)

    # Search for candidates
    print(f"Searching Wikipedia for: {args.query}", file=sys.stderr)
    try:
        search_results = search_wikipedia_candidates(session, args.query, limit=3)
    except Exception as e:
        print(f"Error: Wikipedia search failed: {e}", file=sys.stderr)
        return 1

    if not search_results:
        print("No search results found", file=sys.stderr)
        return 0

    print(f"Found {len(search_results)} candidates:", file=sys.stderr)
    for i, result in enumerate(search_results, 1):
        print(f"  {i}. {result['title']}", file=sys.stderr)

    # Check if API key is available for LLM disambiguation
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nANTHROPIC_API_KEY not set - skipping LLM disambiguation", file=sys.stderr)
        print("Set API key to run full disambiguation with confidence scoring", file=sys.stderr)
        return 2

    # Run disambiguation
    client = Anthropic(api_key=api_key)
    try:
        decision = disambiguate_search_results(
            entity_name=args.query,
            entity_type=args.entity_type,
            transcript_context=args.context,
            video_topic=args.video_topic,
            search_results=search_results,
            session=session,
            client=client,
            cache=cache
        )
    except Exception as e:
        print(f"Error: Disambiguation failed: {e}", file=sys.stderr)
        return 1

    # Print decision
    print("\n=== Disambiguation Decision ===", file=sys.stderr)
    print(json.dumps(decision.model_dump(), indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
