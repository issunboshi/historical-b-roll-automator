#!/usr/bin/env python3
"""
enrich_entities.py

Entity enrichment functions for B-roll automation.

This module provides:
1. Priority scoring - Calculate entity importance scores (0.0-1.2) based on
   type, mention count, and position in transcript
2. Context extraction - Extract transcript context around entity mentions
3. CLI interface - Enrich entities_map.json with priority and context

Priority scores are used in Phase 3 to filter low-value entities.
Context extraction is used in Phase 2 for LLM-generated search queries
and Phase 4 for entity disambiguation.

Usage:
    # As a module
    from tools.enrich_entities import calculate_priority, TYPE_WEIGHTS
    from tools.enrich_entities import extract_entity_context, enrich_entities

    # Priority scoring
    score = calculate_priority(entity, transcript_duration_seconds)

    # Context extraction
    context = extract_entity_context(srt_cues, entity_occurrences, window_cues=3)

    # Full enrichment
    enriched = enrich_entities(entities_map, srt_path)

    # As a CLI
    python tools/enrich_entities.py --map entities_map.json --srt video.srt --out enriched_entities.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from typing import Dict, List, Tuple

# =============================================================================
# Priority Scoring Constants and Functions (Plan 01-01)
# =============================================================================

# Type weights for entity priority scoring
# Higher weights = more likely to be visually interesting B-roll subjects
TYPE_WEIGHTS: Dict[str, float] = {
    "people": 1.0,        # Highest priority - faces are engaging
    "events": 0.9,        # Historical events have strong visual potential
    "organizations": 0.7, # Companies, groups - moderate visual interest
    "concepts": 0.6,      # Abstract concepts - harder to visualize
    "places": 0.3,        # Lowest - often context rather than subject
}

# Default weight for unknown entity types
DEFAULT_TYPE_WEIGHT = 0.5

# Maximum priority score (cap)
MAX_PRIORITY_SCORE = 1.2


def srt_time_to_seconds(timecode: str) -> float:
    """Convert SRT timecode 'HH:MM:SS,mmm' to float seconds.

    Args:
        timecode: SRT format timecode string (e.g., '01:23:45,678')

    Returns:
        Time in seconds as float. Returns 0.0 for invalid formats.

    Examples:
        >>> srt_time_to_seconds('00:01:30,500')
        90.5
        >>> srt_time_to_seconds('invalid')
        0.0
    """
    pattern = re.compile(r"^\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*$")
    match = pattern.match(timecode)
    if not match:
        return 0.0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    milliseconds = int(match.group(4))

    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def mention_multiplier(mention_count: int) -> float:
    """Calculate mention multiplier with diminishing returns.

    Args:
        mention_count: Number of times entity is mentioned in transcript.

    Returns:
        Multiplier value:
        - 0-1 mentions: 1.0x
        - 2 mentions: 1.3x
        - 3 mentions: 1.5x
        - 4+ mentions: 1.6x (max)

    Examples:
        >>> mention_multiplier(1)
        1.0
        >>> mention_multiplier(4)
        1.6
    """
    if mention_count <= 1:
        return 1.0
    elif mention_count == 2:
        return 1.3
    elif mention_count == 3:
        return 1.5
    else:  # 4+
        return 1.6


def position_multiplier(first_position_pct: float) -> float:
    """Calculate position multiplier based on first mention position.

    Early mentions (first 20% of transcript) get a boost because
    entities introduced early are often central to the narrative.

    Args:
        first_position_pct: Position of first mention as fraction (0.0-1.0).
                           0.0 = start, 1.0 = end.

    Returns:
        Multiplier value:
        - Position <= 20%: 1.1x (early mention boost)
        - Position > 20%: 1.0x (no boost)

    Examples:
        >>> position_multiplier(0.1)  # 10% into transcript
        1.1
        >>> position_multiplier(0.5)  # 50% into transcript
        1.0
    """
    if first_position_pct <= 0.2:
        return 1.1
    else:
        return 1.0


def calculate_priority(entity: Dict, transcript_duration_seconds: float) -> float:
    """Calculate priority score for an entity.

    Formula: base_type_weight * mention_multiplier * position_multiplier
    Capped at 1.2 maximum.

    Args:
        entity: Entity dict with structure:
            {
                "entity_type": str,  # "people", "events", etc.
                "occurrences": [{"timecode": "HH:MM:SS,mmm", ...}, ...]
            }
        transcript_duration_seconds: Total transcript duration in seconds.

    Returns:
        Priority score in range 0.0-1.2.
        Returns 0.0 for entities with no occurrences.

    Examples:
        >>> entity = {"entity_type": "people", "occurrences": [{"timecode": "00:01:00,000"}]}
        >>> calculate_priority(entity, 600.0)  # 10 min transcript
        1.1  # 1.0 * 1.0 * 1.1 (early mention)
    """
    occurrences = entity.get("occurrences", [])

    # Edge case: no occurrences
    if not occurrences:
        return 0.0

    # Get base type weight
    entity_type = entity.get("entity_type", "")
    base_weight = TYPE_WEIGHTS.get(entity_type, DEFAULT_TYPE_WEIGHT)

    # Calculate mention multiplier
    mention_count = len(occurrences)
    mention_mult = mention_multiplier(mention_count)

    # Calculate position multiplier based on first occurrence
    first_timecode = occurrences[0].get("timecode", "00:00:00,000")
    first_time_seconds = srt_time_to_seconds(first_timecode)

    # Handle zero duration edge case (treat all positions as early)
    if transcript_duration_seconds <= 0:
        first_position_pct = 0.0
    else:
        first_position_pct = first_time_seconds / transcript_duration_seconds

    position_mult = position_multiplier(first_position_pct)

    # Calculate raw score
    raw_score = base_weight * mention_mult * position_mult

    # Cap at maximum
    return min(raw_score, MAX_PRIORITY_SCORE)


# =============================================================================
# Context Extraction Constants and Functions (Plan 01-02)
# =============================================================================

# Regex to match speaker labels like "Speaker 1", "Speaker 2", etc.
SPEAKER_LABEL_RE = re.compile(r"^\s*Speaker\s+\d+\s*$", re.IGNORECASE | re.MULTILINE)
# Regex to collapse multiple whitespace into single space
WHITESPACE_RE = re.compile(r"\s+")


def _strip_speaker_labels(text: str) -> str:
    """Remove speaker labels from text.

    Handles lines like "Speaker 1", "Speaker 2" that are common in
    transcript exports.
    """
    lines = text.split("\n")
    cleaned = [line for line in lines if not SPEAKER_LABEL_RE.match(line)]
    return "\n".join(cleaned)


def _collapse_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters to single space."""
    return WHITESPACE_RE.sub(" ", text).strip()


def extract_single_context(
    srt_cues: list,
    cue_idx: int,
    window_cues: int = 3,
) -> Tuple[int, int, str]:
    """Extract context window around a single cue.

    Args:
        srt_cues: List of SrtCue objects (must have .index and .text attributes)
        cue_idx: The 1-based cue index to center the window on
        window_cues: Number of cues before and after to include (default 3)

    Returns:
        Tuple of (start_idx, end_idx, context_text) where:
        - start_idx: The minimum cue index included (1-based)
        - end_idx: The maximum cue index included (1-based)
        - context_text: The concatenated and cleaned text

        If cue_idx is not found, returns (-1, -1, "")
    """
    # Build index map for efficient lookup
    cue_map: Dict[int, object] = {cue.index: cue for cue in srt_cues}

    if cue_idx not in cue_map:
        return (-1, -1, "")

    # Determine all valid cue indices
    all_indices = sorted(cue_map.keys())
    if not all_indices:
        return (-1, -1, "")

    min_idx = all_indices[0]
    max_idx = all_indices[-1]

    # Calculate window bounds
    start_idx = max(min_idx, cue_idx - window_cues)
    end_idx = min(max_idx, cue_idx + window_cues)

    # Collect text from cues in range
    texts = []
    for idx in range(start_idx, end_idx + 1):
        if idx in cue_map:
            cue_text = cue_map[idx].text
            # Strip speaker labels
            cleaned = _strip_speaker_labels(cue_text)
            texts.append(cleaned)

    # Join and collapse whitespace
    combined = " ".join(texts)
    context_text = _collapse_whitespace(combined)

    return (start_idx, end_idx, context_text)


def merge_context_windows(
    contexts: List[Tuple[int, int, str]],
) -> str:
    """Merge context windows, handling overlaps.

    Windows are considered overlapping if their index ranges overlap or
    are adjacent (end_a >= start_b - 1). Overlapping windows are merged
    into a single text span. Non-overlapping windows are joined with
    " [...] " separator.

    Args:
        contexts: List of (start_idx, end_idx, context_text) tuples

    Returns:
        Merged context string
    """
    if not contexts:
        return ""

    if len(contexts) == 1:
        return contexts[0][2]

    # Sort by start index
    sorted_contexts = sorted(contexts, key=lambda x: x[0])

    # Merge overlapping ranges into groups
    # Each merged entry: (merged_start, merged_end, combined_text)
    merged: List[Tuple[int, int, str]] = []
    current_start, current_end, current_text = sorted_contexts[0]

    for start_idx, end_idx, text in sorted_contexts[1:]:
        # Check if this window overlaps or is adjacent to current
        if start_idx <= current_end + 1:
            # Overlapping or adjacent - extend the current range
            current_end = max(current_end, end_idx)
            current_text = _collapse_whitespace(current_text + " " + text)
        else:
            # Gap - save current and start new
            merged.append((current_start, current_end, current_text))
            current_start, current_end, current_text = start_idx, end_idx, text

    # Don't forget the last one
    merged.append((current_start, current_end, current_text))

    # Join non-overlapping groups with separator
    return " [...] ".join(ctx[2] for ctx in merged)


def extract_entity_context(
    srt_cues: list,
    entity_occurrences: list,
    window_cues: int = 3,
) -> str:
    """Extract transcript context for all occurrences of an entity.

    For each occurrence, extracts a window of cues before and after.
    Multiple occurrences with overlapping windows are merged to avoid
    duplicate text. Non-overlapping contexts are joined with " [...] ".

    Args:
        srt_cues: List of SrtCue objects (must have .index and .text attributes)
        entity_occurrences: List of dicts with 'cue_idx' key (1-based index)
        window_cues: Number of cues before and after each mention (default 3)
                     Window of 3 = 7 cues total = ~100-150 words

    Returns:
        Combined context string for all occurrences of the entity.
        Returns empty string if no valid occurrences.
    """
    if not entity_occurrences:
        return ""

    # Build index set for validation
    valid_indices = {cue.index for cue in srt_cues}
    if not valid_indices:
        return ""

    # Extract contexts for each valid occurrence
    contexts: List[Tuple[int, int, str]] = []

    for occ in entity_occurrences:
        cue_idx = occ.get("cue_idx")
        if cue_idx is None or cue_idx not in valid_indices:
            continue

        start_idx, end_idx, text = extract_single_context(
            srt_cues, cue_idx, window_cues
        )

        if start_idx >= 0 and text:
            contexts.append((start_idx, end_idx, text))

    if not contexts:
        return ""

    # Merge and return
    return merge_context_windows(contexts)


# =============================================================================
# Main Enrichment Function (Plan 01-03)
# =============================================================================


def enrich_entities(entities_map: Dict, srt_path: str) -> Dict:
    """Enrich entities_map with priority scores and transcript context.

    This function takes an entities_map (from srt_entities.py) and adds:
    - priority: float (0.0-1.2) based on type, mention count, position
    - context: str - transcript text around entity mentions
    - enrichment_status: "success" or "failed"

    Args:
        entities_map: Dict with structure {"entities": {...}, "source_srt": "..."}
        srt_path: Path to the original SRT file (for context extraction)

    Returns:
        A new dict (deep copy) with enriched entities.
        Does not mutate the original entities_map.

    Raises:
        FileNotFoundError: If srt_path does not exist
    """
    # Import parse_srt here to avoid circular imports at module load time
    from tools.srt_entities import parse_srt

    # Deep copy to avoid mutation
    enriched = copy.deepcopy(entities_map)

    # Load SRT cues
    srt_cues = parse_srt(srt_path)

    # Calculate transcript duration from last cue's end timecode
    transcript_duration_seconds = 0.0
    if srt_cues:
        last_cue = srt_cues[-1]
        transcript_duration_seconds = srt_time_to_seconds(last_cue.end)

    entities = enriched.get("entities", {})

    for entity_name, entity_data in entities.items():
        try:
            # Calculate priority score
            priority = calculate_priority(entity_data, transcript_duration_seconds)
            entity_data["priority"] = round(priority, 3)

            # Extract context
            occurrences = entity_data.get("occurrences", [])
            context = extract_entity_context(srt_cues, occurrences, window_cues=3)
            entity_data["context"] = context

            entity_data["enrichment_status"] = "success"

        except Exception as e:
            # Mark as failed but continue with other entities
            entity_data["priority"] = 0.0
            entity_data["context"] = ""
            entity_data["enrichment_status"] = "failed"
            print(f"Warning: Failed to enrich entity '{entity_name}': {e}", file=sys.stderr)

    return enriched


# =============================================================================
# CLI Interface (Plan 01-03)
# =============================================================================


def main(argv: List[str] = None) -> int:
    """CLI entry point for entity enrichment.

    Usage:
        python tools/enrich_entities.py --map entities_map.json --srt video.srt [--out enriched.json]

    Returns:
        0 on success, 1 on general error, 2 on missing file
    """
    parser = argparse.ArgumentParser(
        description="Enrich entities with priority scores and transcript context"
    )
    parser.add_argument(
        "--map",
        required=True,
        help="Path to entities_map.json (from srt_entities.py)"
    )
    parser.add_argument(
        "--srt",
        required=True,
        help="Path to original SRT file (for context extraction)"
    )
    parser.add_argument(
        "--out",
        help="Output path (default: enriched_entities.json in same dir as --map)"
    )

    args = parser.parse_args(argv)

    # Validate SRT file exists
    if not os.path.exists(args.srt):
        print(f"Error: SRT file not found: {args.srt}", file=sys.stderr)
        return 2

    # Validate map file exists
    if not os.path.exists(args.map):
        print(f"Error: entities_map not found: {args.map}", file=sys.stderr)
        return 2

    # Determine output path
    if args.out:
        out_path = args.out
    else:
        map_dir = os.path.dirname(os.path.abspath(args.map))
        out_path = os.path.join(map_dir, "enriched_entities.json")

    # Load entities_map
    try:
        with open(args.map, "r", encoding="utf-8") as f:
            entities_map = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {args.map}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: Failed to read {args.map}: {e}", file=sys.stderr)
        return 1

    # Handle empty entities
    entities = entities_map.get("entities", {})
    if not entities:
        print(f"Warning: No entities found in {args.map}", file=sys.stderr)
        # Still write the (empty) enriched file
        enriched = copy.deepcopy(entities_map)
    else:
        # Enrich entities
        try:
            enriched = enrich_entities(entities_map, args.srt)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"Error: Failed to enrich entities: {e}", file=sys.stderr)
            return 1

    # Write output atomically (temp file + rename)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)

    try:
        # Write to temp file first
        fd, temp_path = tempfile.mkstemp(suffix=".json", dir=out_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(enriched, f, ensure_ascii=False, indent=2)
            # Atomic rename
            os.replace(temp_path, out_path)
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as e:
        print(f"Error: Failed to write {out_path}: {e}", file=sys.stderr)
        return 1

    # Success summary
    entity_count = len(enriched.get("entities", {}))
    success_count = sum(
        1 for e in enriched.get("entities", {}).values()
        if e.get("enrichment_status") == "success"
    )
    print(f"Enriched {success_count}/{entity_count} entities")
    print(f"Output: {os.path.abspath(out_path)}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
