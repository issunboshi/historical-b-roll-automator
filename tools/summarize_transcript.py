#!/usr/bin/env python3
"""
summarize_transcript.py

Analyse enriched entities + transcript samples to produce a transcript summary
containing topic, era, pervasive entities, and entity clusters.

This powers downstream quality improvements:
- Era context improves disambiguation (avoids picking wrong-century matches)
- Pervasive entity detection enables frequency capping in XML generation
- Entity clusters enable deduplication of transcription variants

Usage:
    python tools/summarize_transcript.py \\
        --map enriched_entities.json --srt video.srt --out transcript_summary.json

Output: transcript_summary.json with structure:
    {
        "topic": "The Indian Rebellion of 1857...",
        "era": "1857, British colonial India",
        "era_year_range": [1850, 1860],
        "key_themes": ["sepoy mutiny", ...],
        "pervasive_entities": ["United Kingdom", "India"],
        "entity_clusters": [["Mangal Pandey", "Pandey", "Mandel Pandey"], ...]
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

from anthropic import Anthropic
from pydantic import BaseModel, Field


# =============================================================================
# Pydantic Schemas for Structured Output
# =============================================================================


class EntityCluster(BaseModel):
    """A group of entity names that refer to the same real-world entity."""
    names: List[str] = Field(
        description="List of entity names that refer to the same entity "
                    "(e.g. spelling variants, partial names, historical vs modern names). "
                    "Order: canonical name first, then variants."
    )


class TranscriptSummary(BaseModel):
    """Summary of a video transcript for downstream B-roll processing."""
    topic: str = Field(
        description="One-sentence description of the video's topic"
    )
    era: str = Field(
        description="Time period and setting, e.g. '1857, British colonial India, mid-19th century'"
    )
    era_year_range: List[int] = Field(
        description="Approximate [start_year, end_year] range for the primary era discussed",
        min_length=2,
        max_length=2,
    )
    key_themes: List[str] = Field(
        description="3-5 key themes or events discussed in the video"
    )
    pervasive_entities: List[str] = Field(
        description="Entity names that are background/setting entities too broad for "
                    "useful b-roll (e.g. country names mentioned 10+ times as context, "
                    "not as the subject). Only include entities that appear frequently "
                    "but are too generic to find good images for."
    )
    entity_clusters: List[EntityCluster] = Field(
        description="Groups of entity names from the list that refer to the same "
                    "real-world entity (spelling variants, partial vs full names, "
                    "transliteration differences). Only include actual duplicates."
    )


# =============================================================================
# SRT Parsing (lightweight, just for sampling)
# =============================================================================


def parse_srt_cues(srt_path: str) -> List[dict]:
    """Parse SRT into list of {index, start, end, text} dicts."""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)
    cues = []

    for block in blocks:
        lines = [ln.strip("\ufeff").strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue

        # Find timecode line
        tc_line = None
        tc_idx = None
        for i, line in enumerate(lines):
            if "-->" in line:
                tc_line = line
                tc_idx = i
                break

        if tc_line is None:
            continue

        # Parse timecodes
        match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            tc_line,
        )
        if not match:
            continue

        text = " ".join(lines[tc_idx + 1:])
        cues.append({
            "index": len(cues) + 1,
            "start": match.group(1),
            "end": match.group(2),
            "text": text,
        })

    return cues


def sample_transcript(cues: List[dict]) -> str:
    """Sample ~35 cues from transcript for LLM context.

    Strategy: first 15 + 10 from middle (25/50/75 percentiles) + last 10.
    """
    n = len(cues)
    if n <= 35:
        sampled = cues
    else:
        # First 15
        first = cues[:15]

        # Middle samples at 25th, 50th, 75th percentiles
        middle_indices = set()
        for pct in [0.25, 0.50, 0.75]:
            center = int(n * pct)
            # Take ~3-4 consecutive cues around each percentile
            for offset in range(-1, 3):
                idx = center + offset
                if 15 <= idx < n - 10:
                    middle_indices.add(idx)

        # If we got fewer than 10 middle cues, add more around the median
        if len(middle_indices) < 10:
            median = n // 2
            for offset in range(-5, 6):
                if len(middle_indices) >= 10:
                    break
                idx = median + offset
                if 15 <= idx < n - 10:
                    middle_indices.add(idx)

        middle = [cues[i] for i in sorted(middle_indices)]

        # Last 10
        last = cues[-10:]

        sampled = first + middle + last

    lines = []
    for cue in sampled:
        lines.append(f"[{cue['start']}] {cue['text']}")
    return "\n".join(lines)


def format_entity_summary(entities: dict) -> str:
    """Format entities for the LLM prompt, sorted by mention count."""
    entries = []
    for name, data in entities.items():
        etype = data.get("entity_type", "unknown")
        mentions = len(data.get("occurrences", []))
        priority = data.get("priority", 0.0)
        entries.append((mentions, name, etype, priority))

    entries.sort(key=lambda x: -x[0])

    lines = []
    for mentions, name, etype, priority in entries:
        lines.append(f'"{name}" (type: {etype}, mentions: {mentions}, priority: {priority:.1f})')
    return "\n".join(lines)


# =============================================================================
# LLM Summary Generation
# =============================================================================


def generate_summary(
    entities: dict,
    transcript_sample: str,
    client: Anthropic,
) -> TranscriptSummary:
    """Generate transcript summary using Claude structured outputs."""
    entity_text = format_entity_summary(entities)

    prompt = f"""Analyse this video transcript and its extracted entities to produce a structured summary.

TRANSCRIPT SAMPLE (representative cues from beginning, middle, and end):
{transcript_sample}

EXTRACTED ENTITIES (sorted by mention count):
{entity_text}

Based on the transcript and entity list:

1. TOPIC: Describe the video's topic in one sentence.

2. ERA: Identify the primary historical era/time period discussed. Be specific about years and setting.

3. ERA_YEAR_RANGE: Provide the approximate [start_year, end_year] for the primary era.
   - For historical content: the era being discussed (e.g. [1850, 1860] for 1857 Rebellion)
   - For current events: [current_year - 2, current_year]
   - For timeless topics: [1900, 2025]

4. KEY_THEMES: List 3-5 key themes or events.

5. PERVASIVE_ENTITIES: Identify entities that are:
   - Mentioned very frequently (typically 5+ times)
   - Background/setting entities (countries, broad regions) rather than specific subjects
   - Too generic to find useful, specific b-roll images for
   Do NOT include the main subject of the video, even if mentioned frequently.
   Only include entities where generic Wikipedia images would be unhelpful.

6. ENTITY_CLUSTERS: Group entity names that refer to the SAME real-world entity.
   Common patterns:
   - Spelling variants from transcription: "Mangal Pandey" / "Mandel Pandey"
   - Partial vs full names: "Pandey" / "Mangal Pandey"
   - Historical vs modern names: "Cornpore" / "Kanpur" / "Cawnpore"
   - With/without titles: "Queen Victoria" / "Victoria"
   Put the most complete/correct name first in each cluster.
   Only group names that genuinely refer to the same entity."""

    response = client.beta.messages.parse(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format=TranscriptSummary,
    )

    return response.parsed_output


# =============================================================================
# CLI
# =============================================================================


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate transcript summary (topic, era, pervasive entities, clusters)"
    )
    parser.add_argument(
        "--map", required=True,
        help="Path to enriched_entities.json"
    )
    parser.add_argument(
        "--srt", required=True,
        help="Path to original SRT transcript"
    )
    parser.add_argument(
        "--out",
        help="Output path (default: transcript_summary.json in same dir as --map)"
    )
    args = parser.parse_args(argv)

    # Validate inputs
    map_path = Path(args.map)
    srt_path = Path(args.srt)

    if not map_path.exists():
        print(f"Error: entities file not found: {map_path}", file=sys.stderr)
        return 1
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    # Load entities
    with open(map_path, "r", encoding="utf-8") as f:
        entities_map = json.load(f)
    entities = entities_map.get("entities", {})

    if not entities:
        print("Warning: No entities found", file=sys.stderr)
        return 1

    # Parse and sample transcript
    print(f"Parsing SRT: {srt_path}")
    cues = parse_srt_cues(str(srt_path))
    print(f"Parsed {len(cues)} cues")

    transcript_sample = sample_transcript(cues)
    print(f"Sampled transcript ({len(transcript_sample.splitlines())} lines)")

    # Generate summary
    print("Generating transcript summary via LLM...")
    client = Anthropic(api_key=api_key)
    summary = generate_summary(entities, transcript_sample, client)

    # Convert to dict for JSON output
    result = {
        "topic": summary.topic,
        "era": summary.era,
        "era_year_range": summary.era_year_range,
        "key_themes": summary.key_themes,
        "pervasive_entities": summary.pervasive_entities,
        "entity_clusters": [c.names for c in summary.entity_clusters],
    }

    # Determine output path
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = map_path.parent / "transcript_summary.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\nTranscript Summary:")
    print(f"  Topic: {result['topic']}")
    print(f"  Era: {result['era']} ({result['era_year_range'][0]}-{result['era_year_range'][1]})")
    print(f"  Themes: {', '.join(result['key_themes'])}")
    print(f"  Pervasive entities: {', '.join(result['pervasive_entities']) or '(none)'}")
    print(f"  Entity clusters: {len(result['entity_clusters'])}")
    for cluster in result['entity_clusters']:
        print(f"    - {' / '.join(cluster)}")
    print(f"\nOutput: {out_path}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
