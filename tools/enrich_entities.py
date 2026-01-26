#!/usr/bin/env python3
"""
enrich_entities.py

Functions to enrich entity data with transcript context.

This module provides context extraction for entities found in SRT transcripts.
The extracted context (~100-150 words per mention) is used downstream for:
- Phase 2: LLM-generated search queries
- Phase 4: Entity disambiguation

Usage:
    from tools.enrich_entities import extract_entity_context

    context = extract_entity_context(srt_cues, entity_occurrences, window_cues=3)
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

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
