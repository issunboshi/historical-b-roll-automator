"""
Review and override file operations for disambiguation.

Handles reading/writing of disambiguation review files and manual overrides.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.models.disambiguation import DisambiguationReviewEntry


def write_review_file(entries: List[DisambiguationReviewEntry], output_path: Path) -> None:
    """Write disambiguation review file for human oversight.

    Only includes entities with confidence 4-6 (needs review).

    Output format:
    {
        "generated": "ISO timestamp",
        "instructions": "How to override...",
        "entities": [
            {
                "entity_name": "...",
                "entity_type": "...",
                "candidates": [...],
                "chosen_article": "...",
                "confidence": N,
                "rationale": "...",
                "transcript_context": "...",
                "video_topic": "...",
                "match_quality": "..."
            }
        ]
    }

    Uses atomic write pattern (tempfile + os.replace) for safe output.
    Sorts entities by confidence (lowest first for easier review).

    Args:
        entries: List of DisambiguationReviewEntry objects
        output_path: Path to output review JSON file
    """
    # Sort by confidence (lowest first for easier review)
    sorted_entries = sorted(entries, key=lambda e: e.confidence)

    review_data = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "instructions": (
            "Review entities below where disambiguation was uncertain (confidence 4-6). "
            "To override a choice, add an entry to disambiguation_overrides.json with format: "
            '{"entity_name": "Correct_Wikipedia_Article_Title"}'
        ),
        "entities": [entry.model_dump() for entry in sorted_entries],
    }

    # Atomic write pattern: write to temp file, then replace
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=output_path.parent, delete=False, suffix=".tmp"
    ) as tmp_file:
        json.dump(review_data, tmp_file, indent=2)
        tmp_name = tmp_file.name

    # Atomic replace
    os.replace(tmp_name, output_path)


def load_overrides(override_path: Path) -> Dict[str, str]:
    """Load manual disambiguation overrides.

    Override file format: {"entity_name": "Wikipedia_Article_Title"}
    Returns empty dict if file doesn't exist.

    Ignores keys starting with underscore (for comments/examples).

    Args:
        override_path: Path to overrides JSON file

    Returns:
        Dict mapping entity names to Wikipedia article titles
    """
    if not override_path.exists():
        return {}

    with open(override_path, "r") as f:
        data = json.load(f)

    # Filter out comment/example keys (start with underscore)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_override(entity_name: str, overrides: Dict[str, str]) -> Optional[str]:
    """Check if entity has manual override.

    Returns Wikipedia article title if override exists, None otherwise.
    Overrides take precedence over LLM disambiguation.

    Args:
        entity_name: Entity name to check
        overrides: Override dict from load_overrides()

    Returns:
        Wikipedia article title if override exists, None otherwise
    """
    return overrides.get(entity_name)


def create_override_entry(entity_name: str, wikipedia_title: str) -> Dict[str, str]:
    """Create override entry for manual correction.

    Returns dict suitable for adding to overrides file.

    Args:
        entity_name: Entity name to override
        wikipedia_title: Correct Wikipedia article title

    Returns:
        Dict with single key-value pair for override
    """
    return {entity_name: wikipedia_title}


def save_interactive_overrides(
    new_overrides: Dict[str, str],
    override_path: Path,
) -> int:
    """Merge new interactive overrides into the existing overrides file.

    Reads the existing file (if any), merges new entries (new wins on conflict),
    and writes back atomically.

    Args:
        new_overrides: Dict mapping entity names to Wikipedia article titles
        override_path: Path to disambiguation_overrides.json

    Returns:
        Number of overrides written (new + existing)
    """
    if not new_overrides:
        return 0

    # Load existing overrides
    existing: Dict[str, str] = {}
    if override_path.exists():
        try:
            with open(override_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Merge: new overrides win on conflict
    existing.update(new_overrides)

    # Atomic write
    override_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=override_path.parent, delete=False, suffix=".tmp"
    ) as tmp_file:
        json.dump(existing, tmp_file, indent=2, ensure_ascii=False)
        tmp_name = tmp_file.name

    os.replace(tmp_name, override_path)
    return len(existing)
