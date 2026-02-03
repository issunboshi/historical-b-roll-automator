#!/usr/bin/env python3
"""
download_entities.py

Read entities_map.json, download images for each entity using the existing
Wikipedia downloader, and update the map with image file paths and license data.

Usage:
  python tools/download_entities.py --map entities_map.json --images-per-entity 3

Parallel downloads:
  python tools/download_entities.py --map entities_map.json -j 4  # 4 concurrent downloads
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import shutil
import subprocess
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

# Import srt_time_to_seconds for position calculation (dual import fallback)
try:
    from tools.enrich_entities import srt_time_to_seconds
except ImportError:
    from enrich_entities import srt_time_to_seconds

# Disambiguation imports (dual fallback pattern)
try:
    from tools.disambiguation import (
        search_wikipedia_candidates,
        is_disambiguation_page,
        fetch_candidate_info,
        disambiguate_search_results,
        load_overrides,
        write_review_file,
        process_disambiguation_result,
        log_disambiguation_decision,
        DisambiguationReviewEntry,
    )
except ImportError:
    from disambiguation import (
        search_wikipedia_candidates,
        is_disambiguation_page,
        fetch_candidate_info,
        disambiguate_search_results,
        load_overrides,
        write_review_file,
        process_disambiguation_result,
        log_disambiguation_decision,
        DisambiguationReviewEntry,
    )


# Thread-safe print and logging
_print_lock = threading.Lock()
logger = logging.getLogger(__name__)

# Thread-safe storage for review entries
_review_entries_lock = threading.Lock()
_review_entries: List[DisambiguationReviewEntry] = []


def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with _print_lock:
        print(*args, **kwargs)


def setup_logging(verbose: bool):
    """Setup logging based on verbose flag.

    Args:
        verbose: If True, show INFO level logs (per-entity skip messages).
                If False, show only WARNING and above.
    """
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(message)s',
        stream=sys.stderr
    )


def safe_folder_name(name: str) -> str:
    import re
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    return name or "untitled"


def should_skip_entity(
    entity_name: str,
    entity_data: Dict,
    min_priority: float,
    transcript_duration: float
) -> Tuple[bool, str]:
    """
    Determine if an entity should be skipped based on priority rules.

    Args:
        entity_name: Name of the entity
        entity_data: Entity payload with entity_type, priority, occurrences
        min_priority: Minimum priority threshold (0.0 disables filtering)
        transcript_duration: Total transcript duration in seconds

    Returns:
        Tuple of (should_skip: bool, skip_reason: str)
        - (False, ""): Entity should be downloaded
        - (True, reason): Entity should be skipped with explanation
    """
    # Guard: Filtering disabled
    if min_priority <= 0.0:
        return (False, "")

    # Get entity attributes
    entity_type = entity_data.get("entity_type", "").lower()
    priority = entity_data.get("priority", 0.0)
    occurrences = entity_data.get("occurrences", [])
    mention_count = len(occurrences)

    # Guard: People always download
    if entity_type == "people":
        return (False, "")

    # Guard: Events always download
    if entity_type == "events":
        return (False, "")

    # Places: Special rules for mention count and position
    if entity_type == "places":
        # Calculate first mention position
        first_position_pct = 0.0
        if occurrences and transcript_duration > 0:
            first_timecode = occurrences[0].get("timecode", "00:00:00,000")
            first_time_seconds = srt_time_to_seconds(first_timecode)
            first_position_pct = first_time_seconds / transcript_duration

        # Early mention override (first 10%)
        if first_position_pct <= 0.1:
            return (False, "")

        # Multiple mentions override (2+)
        if mention_count >= 2:
            return (False, "")

        # Single late mention - check priority
        if priority < min_priority:
            return (True, f"place with {mention_count} mention(s), not in first 10%")

    # Concepts: Require >= 0.7 priority
    if entity_type == "concepts":
        if priority < 0.7:
            return (True, f"concept priority {priority:.2f} < 0.70")

    # Default: Check priority threshold
    if priority < min_priority:
        return (True, f"priority {priority:.2f} < {min_priority:.2f}")

    # No skip reason - download this entity
    return (False, "")


def get_search_terms(entity_name: str, payload: Dict) -> List[str]:
    """
    Extract search terms from entity payload's search_strategies field.

    Returns list of search terms to try in order:
    1. best_title (if valid)
    2. Each valid query from validated_queries
    3. Original entity_name as fallback

    If no search_strategies field exists, returns [entity_name] for backward compatibility.
    """
    search_strategies = payload.get("search_strategies")
    if not search_strategies:
        # Backward compatibility: no strategies means use entity name
        return [entity_name]

    terms = []

    # Add best_title if valid
    best_title = search_strategies.get("best_title")
    best_title_valid = search_strategies.get("best_title_valid", False)
    if best_title and best_title_valid:
        terms.append(best_title)

    # Add validated queries
    validated_queries = search_strategies.get("validated_queries", [])
    for vq in validated_queries:
        if vq.get("valid") and vq.get("query"):
            query = vq["query"]
            # Avoid duplicates (e.g., best_title might match a query)
            if query not in terms:
                terms.append(query)

    # Always add original entity name as fallback if not already present
    if entity_name not in terms:
        terms.append(entity_name)

    return terms


def resolve_output_dir() -> Path:
    # Reuse downloader's resolution order via env/config if available;
    # otherwise default to current directory.
    env_out = os.environ.get("WIKI_IMG_OUTPUT_DIR", "").strip()
    if env_out:
        return Path(env_out).expanduser().resolve()
    # Look for config files used by the downloader
    candidates = [
        Path.cwd() / ".wikipedia_image_downloader.ini",
        Path.home() / ".wikipedia_image_downloader.ini",
        Path.home() / ".config" / "wikipedia_image_downloader" / "config.ini",
    ]
    import configparser
    parser = configparser.ConfigParser()
    for cfg in candidates:
        if cfg.exists():
            parser.read(cfg)
            if parser.has_section("settings"):
                out = parser.get("settings", "output_dir", fallback="").strip()
                if out:
                    return Path(out).expanduser().resolve()
    return Path(".").resolve()


def read_download_summary(entity_dir: Path) -> List[Dict[str, str]]:
    """
    Returns list of dict: filename, category, license_short, license_url, source_url
    """
    rows: List[Dict[str, str]] = []
    summary = entity_dir / "DOWNLOAD_SUMMARY.tsv"
    if not summary.exists():
        return rows
    with open(summary, "r", encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 5:
                continue
            filename, category, license_short, license_url, source_url = parts
            rows.append(
                {
                    "filename": filename,
                    "category": category,
                    "license_short": license_short,
                    "license_url": license_url,
                    "source_url": source_url,
                }
            )
    return rows


def read_category_attribution_csv(cat_dir: Path) -> Dict[str, Dict[str, str]]:
    """
    Read ATTRIBUTION.csv if present; return map filename -> row dict.
    """
    csv_path = cat_dir / "ATTRIBUTION.csv"
    if not csv_path.exists():
        return {}
    by_file: Dict[str, Dict[str, str]] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("filename")
            if fn:
                by_file[fn] = row
    return by_file


def download_entity(
    entity_name: str,
    entity_type: str,
    out_dir: Path,
    downloader: Path,
    images_per_entity: int,
    user_agent: str,
    png_width: int,
    delay: float,
    no_svg_to_png: bool,
    worker_id: int,
    total_entities: int,
    current_idx: int,
    search_terms: List[str],
    payload: Dict,
    mention_count: int = 1,
    # New disambiguation parameters
    use_disambiguation: bool = True,
    disambiguation_client: Optional[Anthropic] = None,
    disambiguation_cache: Optional[Cache] = None,
    disambiguation_overrides: Optional[dict] = None,
    video_topic: str = "Unknown video",
    session: Optional[requests.Session] = None,
) -> Tuple[str, bool, Path, Optional[str], Optional[dict]]:
    """
    Download images for a single entity with disambiguation support.

    Returns: (entity_name, success, entity_dir, matched_term, disambiguation_result)
    - matched_term is the search term that succeeded (or None if all failed)
    - disambiguation_result contains confidence, match_quality, rationale if disambiguation was used

    Thread-safe: only uses safe_print for output.
    """
    entity_dir = out_dir / safe_folder_name(entity_name)
    disambiguation_result = None

    # Calculate effective image count based on mention frequency
    effective_images = images_per_entity
    if mention_count >= 3:
        effective_images = min(5, max(images_per_entity, 5))
        safe_print(f"[{current_idx}/{total_entities}]   Multi-mention entity ({mention_count}x): downloading {effective_images} images")

    # Check for pre-computed disambiguation (from disambiguate_entities.py step)
    precomputed_disambig = payload.get("disambiguation")
    if precomputed_disambig and precomputed_disambig.get("wikipedia_title"):
        # Use pre-computed disambiguation result
        wiki_title = precomputed_disambig["wikipedia_title"]
        action = precomputed_disambig.get("action", "download")

        if action == "skip":
            safe_print(f"[{current_idx}/{total_entities}] Skipping {entity_name}: pre-computed skip")
            return (entity_name, False, out_dir / safe_folder_name(entity_name), None, precomputed_disambig)

        # Use pre-computed Wikipedia title as primary search term
        search_terms = [wiki_title] + search_terms
        disambiguation_result = precomputed_disambig
        safe_print(f"[{current_idx}/{total_entities}] Using pre-computed: {entity_name} -> {wiki_title}")

    # Check for manual override
    elif disambiguation_overrides and entity_name in disambiguation_overrides:
        override_title = disambiguation_overrides[entity_name]
        safe_print(f"[{current_idx}/{total_entities}] Using override for {entity_name}: {override_title}")
        search_terms = [override_title]
        disambiguation_result = {
            "disambiguation_source": "manual_override",
            "confidence": 10,
            "match_quality": "high",
            "wikipedia_title": override_title,
        }

    # Run inline disambiguation if enabled and no pre-computed/override
    elif use_disambiguation and disambiguation_client and session:
        transcript_context = payload.get("context", "")

        # Search for top 3 candidates
        best_query = search_terms[0] if search_terms else entity_name
        candidates = search_wikipedia_candidates(session, best_query, limit=3)

        if candidates:
            # Run disambiguation
            decision = disambiguate_search_results(
                entity_name=entity_name,
                entity_type=entity_type,
                transcript_context=transcript_context,
                video_topic=video_topic,
                search_results=candidates,
                session=session,
                client=disambiguation_client,
                cache=disambiguation_cache
            )

            # Process result
            disambiguation_result = process_disambiguation_result(
                decision=decision,
                entity_name=entity_name,
                entity_type=entity_type,
                candidates=fetch_candidate_info([c["title"] for c in candidates], disambiguation_cache),
                transcript_context=transcript_context,
                video_topic=video_topic,
                review_entries=_review_entries  # Thread-safe via lock in process_disambiguation_result
            )

            # Log decision
            log_disambiguation_decision(entity_name, decision, disambiguation_result.get("action", "unknown"))

            # Apply confidence routing
            action = disambiguation_result.get("action", "download")
            if action == "skip":
                safe_print(f"[{current_idx}/{total_entities}] Skipping {entity_name}: low confidence ({decision.confidence})")
                return (entity_name, False, out_dir / safe_folder_name(entity_name), None, disambiguation_result)

            # Use chosen article for download
            if decision.chosen_article:
                search_terms = [decision.chosen_article] + search_terms

    # If the entity output directory already exists, skip the download step
    if entity_dir.exists():
        safe_print(f"[{current_idx}/{total_entities}] Skipping: {entity_name} (already downloaded)")
        # Determine matched_term from existing directory
        # Since we can't know which term was used, assume it was the entity name
        return (entity_name, True, entity_dir, entity_name, disambiguation_result)

    safe_print(f"[{current_idx}/{total_entities}] Downloading: {entity_name}")

    # Try each search term in order; stop at first success
    # (Plan says: try ALL strategies, but in practice we should stop at first success for efficiency)
    best_title = payload.get("search_strategies", {}).get("best_title")

    for search_term in search_terms:
        safe_print(f"[{current_idx}/{total_entities}]   Trying: {search_term}")

        # The downloader creates out_dir/safe_folder_name(search_term)
        search_term_dir = out_dir / safe_folder_name(search_term)

        # Skip if this directory already exists (from previous run or earlier iteration)
        if search_term_dir.exists():
            safe_print(f"[{current_idx}/{total_entities}]   Skipping: {search_term} (already exists)")
            # Check if it has images
            image_count = sum(1 for _ in search_term_dir.rglob("*.png")) + sum(1 for _ in search_term_dir.rglob("*.jpg"))
            if image_count > 0:
                # Success - rename to entity_dir if needed
                if search_term_dir != entity_dir:
                    if entity_dir.exists():
                        # entity_dir exists (from earlier search term) - replace it
                        shutil.rmtree(entity_dir)
                    search_term_dir.rename(entity_dir)
                safe_print(f"[{current_idx}/{total_entities}] Done: {entity_name} (matched: {search_term})")
                return (entity_name, True, entity_dir, search_term, disambiguation_result)
            continue

        try:
            cmd = [
                sys.executable,
                str(downloader),
                search_term,
                "--limit",
                str(effective_images),
                "--user-agent",
                user_agent,
                "--png-width",
                str(png_width),
                "--delay",
                str(delay),
            ]
            # If entity name contains a year/date, disable historical (older-first) priority
            has_year = bool(re.search(r"(?<!\d)(1\d{3}|20\d{2}|21\d{2})(?!\d)", entity_name))
            if has_year:
                cmd.append("--no-historical-priority")
            # If it's a person, prioritize recent images
            if entity_type.lower() == "people":
                cmd.append("--prefer-recent")
            if no_svg_to_png:
                cmd.append("--no-svg-to-png")

            # Capture output to avoid interleaved console output
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Success - check if search_term_dir now exists with images
            if search_term_dir.exists():
                image_count = sum(1 for _ in search_term_dir.rglob("*.png")) + sum(1 for _ in search_term_dir.rglob("*.jpg"))
                if image_count > 0:
                    safe_print(f"[{current_idx}/{total_entities}]   Success with: {search_term} ({image_count} images)")

                    # Rename to entity_dir if different
                    if search_term_dir != entity_dir:
                        search_term_dir.rename(entity_dir)

                    safe_print(f"[{current_idx}/{total_entities}] Done: {entity_name} (matched: {search_term})")
                    return (entity_name, True, entity_dir, search_term, disambiguation_result)
                else:
                    safe_print(f"[{current_idx}/{total_entities}]   No images found for: {search_term}")
            else:
                safe_print(f"[{current_idx}/{total_entities}]   No output for: {search_term}")

        except subprocess.CalledProcessError as e:
            safe_print(f"[{current_idx}/{total_entities}]   Failed: {search_term}")
            continue

    # All search terms failed
    safe_print(f"[{current_idx}/{total_entities}] Failed: {entity_name} - all search terms failed", file=sys.stderr)
    return (entity_name, False, entity_dir, None, disambiguation_result)


def harvest_images(entity_dir: Path) -> List[Dict[str, str]]:
    """
    Read downloaded image info from entity directory.
    Returns list of image metadata dicts.
    """
    summary_rows = read_download_summary(entity_dir)
    if not summary_rows:
        return []

    # Load per-category attribution maps
    cat_attrib: Dict[str, Dict[str, Dict[str, str]]] = {}
    for cat in ("cc_by", "cc_by_sa", "other_cc", "restricted_nonfree", "unknown", "public_domain"):
        cat_dir = entity_dir / cat
        cat_attrib[cat] = read_category_attribution_csv(cat_dir)

    images_payload: List[Dict[str, str]] = []
    seen_paths = set()
    
    for row in summary_rows:
        fn = row["filename"]
        cat = row["category"]
        file_path = entity_dir / cat / fn if cat and (entity_dir / cat / fn).exists() else entity_dir / fn
        
        # Skip raw SVGs; prefer converted PNG if available, otherwise ignore
        if file_path.suffix.lower() == ".svg":
            png_candidate = file_path.with_suffix(".png")
            if png_candidate.exists():
                file_path = png_candidate
                fn = png_candidate.name
            else:
                continue
        
        # Deduplicate by absolute path to ensure rotation uses distinct images
        abs_path_str = str(file_path.resolve())
        if abs_path_str in seen_paths:
            continue
        seen_paths.add(abs_path_str)
        
        entry: Dict[str, str] = {
            "path": str(file_path),
            "filename": fn,
            "category": cat,
            "license_short": row.get("license_short", ""),
            "license_url": row.get("license_url", ""),
            "source_url": row.get("source_url", ""),
            "title": "",
            "author": "",
            "usage_terms": "",
            "suggested_attribution": "",
        }
        
        # Enrich with attribution CSV if available for non-PD
        if cat in cat_attrib and fn in cat_attrib[cat]:
            a = cat_attrib[cat][fn]
            entry["title"] = a.get("title", "")
            entry["author"] = a.get("author", "")
            entry["usage_terms"] = a.get("usage_terms", "")
            entry["suggested_attribution"] = a.get("suggested_attribution", "")
        
        images_payload.append(entry)
    
    return images_payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download images for entities and update entities_map.json",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--map", required=True, help="Path to entities_map.json produced by srt_entities.py")
    parser.add_argument("--images-per-entity", type=int, default=3, help="Max images per entity")
    parser.add_argument("--user-agent", type=str, default="b-roll-pipeline/0.1", help="HTTP User-Agent for downloader")
    parser.add_argument("--png-width", type=int, default=3000, help="PNG width for SVG conversion")
    parser.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion")
    parser.add_argument("--delay", type=float, default=0.1, help="Politeness delay between requests (seconds)")
    parser.add_argument("-j", "--parallel", type=int, default=1,
                        help="Number of parallel downloads (recommended: 4)")
    parser.add_argument("--no-strategies", action="store_true",
                        help="Disable search strategy iteration (use only entity name for backward compatibility)")
    parser.add_argument("--min-priority", type=float, default=0.5,
                        help="Minimum priority threshold (0.0 disables filtering)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show per-entity skip messages")
    parser.add_argument("--no-disambiguation", action="store_true",
                        help="Disable LLM disambiguation (use first search result)")
    parser.add_argument("--overrides", type=str, default="output/disambiguation_overrides.json",
                        help="Path to disambiguation overrides JSON file")
    parser.add_argument("--review-file", type=str, default="output/disambiguation_review.json",
                        help="Path to write disambiguation review file")
    args = parser.parse_args(argv)

    # Setup logging based on verbose flag
    setup_logging(args.verbose)

    # Initialize disambiguation dependencies
    disambiguation_client = None
    disambiguation_cache = None
    disambiguation_overrides = {}

    if not args.no_disambiguation:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, disambiguation disabled", file=sys.stderr)
            args.no_disambiguation = True
        else:
            disambiguation_client = Anthropic(api_key=api_key)
            disambiguation_cache = Cache("/tmp/wikipedia_cache")
            disambiguation_overrides = load_overrides(Path(args.overrides))

    with open(args.map, "r", encoding="utf-8") as f:
        entities_map = json.load(f)
    entities: Dict[str, Dict] = entities_map.get("entities", {})

    # Load montage data if available (to boost image counts for montage entities)
    montage_image_counts: Dict[str, int] = {}
    montage_entities: set = set()
    montages_path = Path(args.map).parent / "montages.json"
    if montages_path.exists():
        try:
            with open(montages_path, "r", encoding="utf-8") as f:
                montages_data = json.load(f)
            for montage in montages_data.get("montage_opportunities", []):
                suggested_count = montage.get("suggested_image_count", 4)
                for entity in montage.get("entities", []):
                    montage_entities.add(entity)
                    # Use maximum if entity appears in multiple montages
                    montage_image_counts[entity] = max(
                        montage_image_counts.get(entity, 0),
                        suggested_count
                    )
            if montage_entities:
                print(f"Loaded {len(montage_entities)} montage entities from {montages_path}")
        except Exception as e:
            print(f"Warning: Failed to load montages: {e}", file=sys.stderr)
    if not entities:
        print("No entities in map.", file=sys.stderr)
        return 2

    out_dir = resolve_output_dir()
    downloader = Path(__file__).resolve().parent / "download_wikipedia_images.py"
    if not downloader.exists():
        print("download_wikipedia_images.py not found.", file=sys.stderr)
        return 2

    # Get transcript duration for position calculations
    transcript_duration = entities_map.get("metadata", {}).get("transcript_duration")
    if transcript_duration is None:
        # Compute from maximum timecode in any entity's occurrences
        max_time = 0.0
        for entity_data in entities.values():
            for occ in entity_data.get("occurrences", []):
                timecode = occ.get("timecode")
                if timecode:
                    time_secs = srt_time_to_seconds(timecode)
                    max_time = max(max_time, time_secs)
        transcript_duration = max_time

    # Filter to entities that need downloading (don't already have images)
    need_download = [
        (name, payload) for name, payload in entities.items()
        if not payload.get("images")
    ]

    if not need_download:
        print("All entities already have images. Nothing to download.")
        return 0

    # Create shared session for Wikipedia API calls
    wiki_session = requests.Session()
    wiki_session.headers.update({
        "User-Agent": f"B-Roll-Finder/1.0 ({args.user_agent})"
    })

    # Extract video topic for disambiguation context
    video_topic = entities_map.get("video_context", "")
    if not video_topic:
        source_srt = entities_map.get("source_srt", "")
        if source_srt:
            video_topic = os.path.splitext(os.path.basename(source_srt))[0]
            video_topic = video_topic.replace("_", " ").replace("-", " ")
        else:
            video_topic = "Unknown video"

    # Apply priority filtering BEFORE parallel execution (thread-safe)
    to_download = []
    skipped_entities = []

    for entity_name, entity_data in need_download:
        priority = entity_data.get("priority", 0.0)
        should_skip, skip_reason = should_skip_entity(
            entity_name,
            entity_data,
            args.min_priority,
            transcript_duration
        )

        if should_skip:
            logger.info(f"Skipping {entity_name}: {skip_reason}")
            skipped_entities.append({
                "name": entity_name,
                "entity_type": entity_data.get("entity_type"),
                "priority": priority,
                "mention_count": len(entity_data.get("occurrences", [])),
                "reason": skip_reason
            })
        else:
            to_download.append((entity_name, entity_data))

    if not to_download and not skipped_entities:
        print("No entities to process.")
        return 0

    total = len(to_download)
    workers = max(1, min(args.parallel, total)) if total > 0 else 1

    print(f"Downloading images for {total} entities using {workers} parallel worker(s)...")
    print(f"Delay between requests: {args.delay}s")
    if args.no_strategies:
        print("Strategy iteration: DISABLED (using entity names only)")
    else:
        print("Strategy iteration: ENABLED (trying LLM-generated search queries)")
    if args.min_priority > 0:
        print(f"Priority filtering: ENABLED (min_priority={args.min_priority})")
    else:
        print("Priority filtering: DISABLED")
    print()

    # Track results: entity_name -> (success, entity_dir, matched_term, disambiguation_result)
    results: Dict[str, Tuple[bool, Path, Optional[str], Optional[dict]]] = {}

    # Track elevated image count statistics
    elevated_count = 0

    # Track montage entity count
    montage_download_count = 0

    if workers == 1:
        # Sequential mode (original behavior, slightly optimized)
        for idx, (entity_name, payload) in enumerate(to_download, start=1):
            entity_type = payload.get("entity_type", "")
            # Get search terms (respects --no-strategies flag)
            if args.no_strategies:
                search_terms = [entity_name]
            else:
                search_terms = get_search_terms(entity_name, payload)
            # Extract mention count from payload
            mention_count = len(payload.get("occurrences", []))
            if mention_count >= 3:
                elevated_count += 1

            # Check for montage-boosted image count
            entity_images = args.images_per_entity
            is_montage = entity_name in montage_image_counts
            if is_montage:
                entity_images = max(entity_images, montage_image_counts[entity_name])
                montage_download_count += 1
                safe_print(f"[{idx}/{total}]   Montage entity: downloading {entity_images} images")

            name, success, entity_dir, matched_term, disambiguation_result = download_entity(
                entity_name=entity_name,
                entity_type=entity_type,
                out_dir=out_dir,
                downloader=downloader,
                images_per_entity=entity_images,
                user_agent=args.user_agent,
                png_width=args.png_width,
                delay=args.delay,
                no_svg_to_png=args.no_svg_to_png,
                worker_id=0,
                total_entities=total,
                current_idx=idx,
                search_terms=search_terms,
                payload=payload,
                mention_count=mention_count,
                use_disambiguation=not args.no_disambiguation,
                disambiguation_client=disambiguation_client,
                disambiguation_cache=disambiguation_cache,
                disambiguation_overrides=disambiguation_overrides,
                video_topic=video_topic,
                session=wiki_session,
            )
            results[name] = (success, entity_dir, matched_term, disambiguation_result)
    else:
        # Parallel mode using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for idx, (entity_name, payload) in enumerate(to_download, start=1):
                entity_type = payload.get("entity_type", "")
                # Get search terms (respects --no-strategies flag)
                if args.no_strategies:
                    search_terms = [entity_name]
                else:
                    search_terms = get_search_terms(entity_name, payload)
                # Extract mention count from payload
                mention_count = len(payload.get("occurrences", []))
                if mention_count >= 3:
                    elevated_count += 1

                # Check for montage-boosted image count
                entity_images = args.images_per_entity
                is_montage = entity_name in montage_image_counts
                if is_montage:
                    entity_images = max(entity_images, montage_image_counts[entity_name])
                    montage_download_count += 1

                future = executor.submit(
                    download_entity,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    out_dir=out_dir,
                    downloader=downloader,
                    images_per_entity=entity_images,
                    user_agent=args.user_agent,
                    png_width=args.png_width,
                    delay=args.delay,
                    no_svg_to_png=args.no_svg_to_png,
                    worker_id=idx % workers,
                    total_entities=total,
                    current_idx=idx,
                    search_terms=search_terms,
                    payload=payload,
                    mention_count=mention_count,
                    use_disambiguation=not args.no_disambiguation,
                    disambiguation_client=disambiguation_client,
                    disambiguation_cache=disambiguation_cache,
                    disambiguation_overrides=disambiguation_overrides,
                    video_topic=video_topic,
                    session=wiki_session,
                )
                futures[future] = entity_name

            # Collect results as they complete
            for future in as_completed(futures):
                entity_name = futures[future]
                try:
                    name, success, entity_dir, matched_term, disambiguation_result = future.result()
                    results[name] = (success, entity_dir, matched_term, disambiguation_result)
                except Exception as e:
                    print(f"Error processing {entity_name}: {e}", file=sys.stderr)
                    results[entity_name] = (False, out_dir / safe_folder_name(entity_name), None, None)
    
    # Harvest results and update entities map
    print()
    print("Harvesting downloaded images...")

    success_count = 0
    fail_count = 0

    # Track strategy stats
    strategy_stats = {
        "best_title": 0,
        "query": 0,
        "fallback": 0,
        "failed": 0,
    }

    for entity_name, payload in entities.items():
        if entity_name not in results:
            continue  # Already had images

        success, entity_dir, matched_term, disambiguation_result = results[entity_name]

        # Track disambiguation metadata
        if disambiguation_result:
            payload["disambiguation"] = {
                "source": disambiguation_result.get("disambiguation_source"),
                "confidence": disambiguation_result.get("confidence"),
                "match_quality": disambiguation_result.get("match_quality"),
                "rationale": disambiguation_result.get("rationale"),
                "candidates_considered": disambiguation_result.get("candidates_considered"),
                "chosen_article": disambiguation_result.get("wikipedia_title"),
            }

        if not success:
            fail_count += 1
            payload["matched_strategy"] = None
            payload["download_status"] = "failed"
            strategy_stats["failed"] += 1
            continue

        images = harvest_images(entity_dir)
        if images:
            payload["images"] = images
            success_count += 1
            payload["download_status"] = "success"

            # Mark montage entities for XML generator
            if entity_name in montage_entities:
                payload["is_montage"] = True
                payload["montage_image_count"] = montage_image_counts.get(entity_name, len(images))

            # Determine which strategy type was used
            if matched_term:
                search_strategies = payload.get("search_strategies", {})
                best_title = search_strategies.get("best_title")
                validated_queries = search_strategies.get("validated_queries", [])

                if best_title and matched_term == best_title:
                    payload["matched_strategy"] = "best_title"
                    strategy_stats["best_title"] += 1
                elif any(vq.get("query") == matched_term for vq in validated_queries):
                    # Find which query index
                    for idx, vq in enumerate(validated_queries):
                        if vq.get("query") == matched_term:
                            payload["matched_strategy"] = f"query_{idx}"
                            strategy_stats["query"] += 1
                            break
                elif matched_term == entity_name:
                    payload["matched_strategy"] = "fallback"
                    strategy_stats["fallback"] += 1
                else:
                    # Unknown strategy (shouldn't happen)
                    payload["matched_strategy"] = "unknown"
            else:
                payload["matched_strategy"] = None
        else:
            # Download succeeded but no images found (e.g., no Wikipedia page)
            fail_count += 1
            payload["matched_strategy"] = None
            payload["download_status"] = "no_images"
            strategy_stats["failed"] += 1

    # Add skipped entities to output JSON
    entities_map["skipped"] = skipped_entities

    # Write updated map
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print("Download Summary")
    print("=" * 60)
    print(f"  Downloaded: {success_count} entities")
    print(f"  Elevated (5 images): {elevated_count} entities")
    if montage_download_count > 0:
        print(f"  Montage entities:    {montage_download_count} entities (extra images for rapid sequences)")
    print(f"  Skipped:    {len(skipped_entities)} entities")
    print(f"  Failed:     {fail_count} entities")
    print("=" * 60)

    # Show strategy breakdown if strategies were used
    if not args.no_strategies and sum(strategy_stats.values()) > 0:
        print()
        print("Strategy breakdown:")
        print(f"  best_title: {strategy_stats['best_title']} entities")
        print(f"  queries:    {strategy_stats['query']} entities")
        print(f"  fallback:   {strategy_stats['fallback']} entities")
        print(f"  failed:     {strategy_stats['failed']} entities")

    # Write review file after all downloads (if disambiguation was used)
    if not args.no_disambiguation and _review_entries:
        review_path = Path(args.review_file)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        write_review_file(_review_entries, review_path)
        print()
        print(f"Disambiguation review file: {review_path}")
        print(f"  Flagged entities: {len(_review_entries)} (confidence 4-6)")

    # Add disambiguation stats to summary
    if not args.no_disambiguation:
        disamb_stats = {
            "auto_accepted": sum(1 for e in entities.values() if e.get("disambiguation", {}).get("confidence", 0) >= 7),
            "flagged": len(_review_entries),
            "skipped": sum(1 for e in entities.values() if e.get("disambiguation", {}).get("match_quality") == "none"),
        }
        print()
        print("Disambiguation summary:")
        print(f"  Auto-accepted (confidence >= 7): {disamb_stats['auto_accepted']}")
        print(f"  Flagged for review (4-6):        {disamb_stats['flagged']}")
        print(f"  Skipped (low confidence):        {disamb_stats['skipped']}")

    print()
    print(f"Updated {args.map}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
