#!/usr/bin/env python3
"""
disambiguate_entities.py

Pre-compute Wikipedia disambiguation for all entities BEFORE downloading.
This allows disambiguation to run with high parallelism, dramatically reducing
total pipeline time.

Usage:
  python tools/disambiguate_entities.py --map strategies_entities.json

This step runs between 'strategies' and 'download' in the pipeline.
Output is written back to the same file with disambiguation results added.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

import requests
from anthropic import Anthropic
from diskcache import Cache

# Disambiguation imports (dual fallback pattern)
try:
    from tools.disambiguation import (
        search_wikipedia_candidates,
        fetch_candidate_info,
        disambiguate_search_results,
        load_overrides,
        process_disambiguation_result,
        DisambiguationReviewEntry,
    )
    from tools.enrich_entities import srt_time_to_seconds
except ImportError:
    from disambiguation import (
        search_wikipedia_candidates,
        fetch_candidate_info,
        disambiguate_search_results,
        load_overrides,
        process_disambiguation_result,
        DisambiguationReviewEntry,
    )
    from enrich_entities import srt_time_to_seconds


# Thread-safe print
_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with _print_lock:
        print(*args, **kwargs)


# Terms that should never be treated as downloadable entities
REJECTED_ENTITY_TERMS = {
    "he", "she", "it", "they", "him", "her", "them", "his", "hers", "its",
    "i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
    "unknown", "someone", "something", "anyone", "anything", "one", "ones",
    "man", "woman", "person", "people", "thing", "things", "stuff",
    "somebody", "anybody", "nobody", "everyone", "everything",
    "a", "an", "the", "this", "that", "these", "those",
    "here", "there", "now", "then", "today", "yesterday", "tomorrow",
}


def should_skip_entity(
    entity_name: str,
    entity_data: Dict,
    min_priority: float,
    transcript_duration: float
) -> Tuple[bool, str]:
    """Determine if an entity should be skipped based on priority rules."""
    normalized_name = entity_name.lower().strip()
    if normalized_name in REJECTED_ENTITY_TERMS:
        return (True, f"rejected term: '{entity_name}'")

    if min_priority <= 0.0:
        return (False, "")

    entity_type = entity_data.get("entity_type", "").lower()
    priority = entity_data.get("priority", 0.0)
    occurrences = entity_data.get("occurrences", [])
    mention_count = len(occurrences)

    if entity_type == "people":
        return (False, "")
    if entity_type == "events":
        return (False, "")

    if entity_type == "places":
        first_position_pct = 0.0
        if occurrences and transcript_duration > 0:
            first_timecode = occurrences[0].get("timecode", "00:00:00,000")
            first_time_seconds = srt_time_to_seconds(first_timecode)
            first_position_pct = first_time_seconds / transcript_duration

        if first_position_pct <= 0.1:
            return (False, "")
        if mention_count >= 2:
            return (False, "")
        if priority < min_priority:
            return (True, f"place with {mention_count} mention(s), not in first 10%")

    if entity_type == "concepts":
        if priority < 0.7:
            return (True, f"concept priority {priority:.2f} < 0.70")

    if priority < min_priority:
        return (True, f"priority {priority:.2f} < {min_priority:.2f}")

    return (False, "")


def get_best_search_query(entity_name: str, payload: Dict) -> str:
    """Get the best search query from entity payload."""
    search_strategies = payload.get("search_strategies")
    if not search_strategies:
        return entity_name

    best_title = search_strategies.get("best_title")
    best_title_valid = search_strategies.get("best_title_valid", False)
    if best_title and best_title_valid:
        return best_title

    validated_queries = search_strategies.get("validated_queries", [])
    for vq in validated_queries:
        if vq.get("valid") and vq.get("query"):
            return vq["query"]

    return entity_name


def disambiguate_single_entity(
    entity_name: str,
    entity_data: Dict,
    video_topic: str,
    session: requests.Session,
    client: Anthropic,
    cache: Cache,
    overrides: dict,
    idx: int,
    total: int,
) -> Tuple[str, Optional[dict]]:
    """
    Run disambiguation for a single entity.

    Returns: (entity_name, disambiguation_result or None)
    """
    entity_type = entity_data.get("entity_type", "")
    transcript_context = entity_data.get("context", "")

    # Check for manual override first
    if entity_name in overrides:
        override_title = overrides[entity_name]
        safe_print(f"[{idx}/{total}] Override: {entity_name} -> {override_title}")
        return (entity_name, {
            "disambiguation_source": "manual_override",
            "confidence": 10,
            "match_quality": "high",
            "wikipedia_title": override_title,
            "action": "download",
            "candidates_considered": [override_title],
            "rationale": "Manual override applied",
        })

    # Get best search query
    best_query = get_best_search_query(entity_name, entity_data)

    # Search Wikipedia
    try:
        candidates = search_wikipedia_candidates(session, best_query, limit=3)
    except Exception as e:
        safe_print(f"[{idx}/{total}] Search failed for {entity_name}: {e}")
        return (entity_name, None)

    if not candidates:
        safe_print(f"[{idx}/{total}] No candidates: {entity_name}")
        return (entity_name, {
            "disambiguation_source": "search",
            "confidence": 0,
            "match_quality": "none",
            "wikipedia_title": None,
            "action": "skip",
            "candidates_considered": [],
            "rationale": "No Wikipedia search results found",
        })

    # Run disambiguation
    try:
        decision = disambiguate_search_results(
            entity_name=entity_name,
            entity_type=entity_type,
            transcript_context=transcript_context,
            video_topic=video_topic,
            search_results=candidates,
            session=session,
            client=client,
            cache=cache,
        )
    except Exception as e:
        safe_print(f"[{idx}/{total}] Disambiguation failed for {entity_name}: {e}")
        return (entity_name, None)

    # Convert decision to result dict
    candidate_info = fetch_candidate_info([c["title"] for c in candidates], cache)

    # Determine action based on confidence
    if decision.confidence >= 7:
        action = "download"
    elif decision.confidence >= 4:
        action = "flag_and_download"
    else:
        action = "skip"

    result = {
        "disambiguation_source": "llm_disambiguation",
        "confidence": decision.confidence,
        "match_quality": decision.match_quality,
        "wikipedia_title": decision.chosen_article if decision.chosen_article else None,
        "action": action,
        "candidates_considered": decision.candidates_considered,
        "rationale": decision.rationale,
    }

    quality_indicator = "✓" if action == "download" else "?" if action == "flag_and_download" else "✗"
    safe_print(f"[{idx}/{total}] {quality_indicator} {entity_name} -> {result['wikipedia_title'] or 'SKIP'} (conf:{decision.confidence})")

    return (entity_name, result)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-compute Wikipedia disambiguation for all entities",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--map", required=True, help="Path to entities_map.json")
    parser.add_argument("-j", "--parallel", type=int, default=10,
                        help="Number of parallel disambiguation workers")
    parser.add_argument("--min-priority", type=float, default=0.5,
                        help="Minimum priority threshold")
    parser.add_argument("--overrides", type=str, default="output/disambiguation_overrides.json",
                        help="Path to disambiguation overrides JSON file")
    parser.add_argument("--cache-dir", type=str, default="/tmp/wikipedia_cache",
                        help="Directory for disambiguation cache")
    args = parser.parse_args(argv)

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    # Initialize client and cache
    client = Anthropic(api_key=api_key)
    cache = Cache(args.cache_dir)
    overrides = load_overrides(Path(args.overrides))

    # Load entities
    with open(args.map, "r", encoding="utf-8") as f:
        entities_map = json.load(f)

    entities: Dict[str, Dict] = entities_map.get("entities", {})
    if not entities:
        print("No entities in map.", file=sys.stderr)
        return 2

    # Get transcript duration
    transcript_duration = entities_map.get("metadata", {}).get("transcript_duration")
    if transcript_duration is None:
        max_time = 0.0
        for entity_data in entities.values():
            for occ in entity_data.get("occurrences", []):
                timecode = occ.get("timecode")
                if timecode:
                    time_secs = srt_time_to_seconds(timecode)
                    max_time = max(max_time, time_secs)
        transcript_duration = max_time

    # Get video topic
    video_topic = entities_map.get("video_context", "")
    if not video_topic:
        source_srt = entities_map.get("source_srt", "")
        if source_srt:
            video_topic = os.path.splitext(os.path.basename(source_srt))[0]
            video_topic = video_topic.replace("_", " ").replace("-", " ")
        else:
            video_topic = "Unknown video"

    # Filter entities that need disambiguation
    to_disambiguate = []
    skipped = []

    for entity_name, entity_data in entities.items():
        # Skip if already has disambiguation
        if entity_data.get("disambiguation"):
            continue

        # Skip if already has images
        if entity_data.get("images"):
            continue

        # Apply priority filtering
        should_skip, skip_reason = should_skip_entity(
            entity_name, entity_data, args.min_priority, transcript_duration
        )

        if should_skip:
            skipped.append({"name": entity_name, "reason": skip_reason})
        else:
            to_disambiguate.append((entity_name, entity_data))

    if not to_disambiguate:
        print("No entities need disambiguation.")
        return 0

    total = len(to_disambiguate)
    workers = min(args.parallel, total)

    print(f"Disambiguating {total} entities using {workers} parallel workers...")
    print(f"Cache: {args.cache_dir}")
    print()

    # Create shared session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "B-Roll-Finder/1.0 (Wikipedia disambiguation)"
    })

    # Run disambiguation in parallel
    results: Dict[str, Optional[dict]] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for idx, (entity_name, entity_data) in enumerate(to_disambiguate, start=1):
            future = executor.submit(
                disambiguate_single_entity,
                entity_name=entity_name,
                entity_data=entity_data,
                video_topic=video_topic,
                session=session,
                client=client,
                cache=cache,
                overrides=overrides,
                idx=idx,
                total=total,
            )
            futures[future] = entity_name

        for future in as_completed(futures):
            entity_name = futures[future]
            try:
                name, result = future.result()
                results[name] = result
            except Exception as e:
                print(f"Error disambiguating {entity_name}: {e}", file=sys.stderr)
                results[entity_name] = None

    # Update entities with disambiguation results
    success_count = 0
    skip_count = 0
    fail_count = 0

    for entity_name, result in results.items():
        if result is None:
            fail_count += 1
            continue

        entities[entity_name]["disambiguation"] = result

        if result["action"] == "skip":
            skip_count += 1
        else:
            success_count += 1

    # Update skipped list
    if "skipped" not in entities_map:
        entities_map["skipped"] = []
    entities_map["skipped"].extend(skipped)

    # Write updated map
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print("Disambiguation Summary")
    print("=" * 60)
    print(f"  Ready to download: {success_count}")
    print(f"  Skipped (low conf): {skip_count}")
    print(f"  Failed:            {fail_count}")
    print(f"  Priority filtered: {len(skipped)}")
    print("=" * 60)
    print()
    print(f"Updated {args.map}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
