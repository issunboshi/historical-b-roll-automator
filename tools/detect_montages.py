#!/usr/bin/env python3
"""
detect_montages.py

Detect montage/collage opportunities in extracted entities.

A montage is appropriate when:
1. Multiple entities are mentioned in quick succession (entity density)
2. A "sweep" event is mentioned (French Revolution, World War II, etc.)
3. List language is used ("leaders like X, Y, and Z")

Usage:
  python tools/detect_montages.py --entities entities_map.json --out montages.json
  python tools/detect_montages.py --srt video.srt --out montages.json  # standalone mode

Env:
  - OPENAI_API_KEY or ANTHROPIC_API_KEY (for standalone SRT analysis)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401


@dataclass
class MontageOpportunity:
    """A detected montage/collage opportunity."""
    montage_id: str
    montage_type: str  # density, sweep_event, enumeration
    timecode: str
    cue_idx: int
    entities: List[str]  # entities that could be in the montage
    reason: str
    suggested_image_count: int
    source_text: Optional[str] = None


# Events that are inherently "broad" and have lots of imagery
SWEEP_EVENTS = {
    # Revolutions
    "french revolution", "american revolution", "russian revolution",
    "industrial revolution", "scientific revolution", "haitian revolution",
    "cuban revolution", "iranian revolution", "chinese revolution",
    # Wars
    "world war i", "world war ii", "world war 1", "world war 2",
    "first world war", "second world war", "cold war", "vietnam war",
    "civil war", "napoleonic wars", "crusades",
    # Eras/Movements
    "renaissance", "enlightenment", "reformation", "middle ages",
    "ancient rome", "ancient greece", "roman empire", "british empire",
    "colonial era", "civil rights movement", "women's suffrage",
    # Broad events
    "great depression", "space race", "manhattan project",
    "age of exploration", "silk road",
}

# Language patterns that suggest enumeration/lists
ENUMERATION_PATTERNS = [
    r"\b(leaders? like|people like|countries like|nations like)\b",
    r"\b(such as|including|among them|for example)\b.*,.*,",
    r"\b(many|several|numerous|various|countless)\s+(people|leaders|countries|nations|figures|artists|scientists)\b",
    r"\b(across|throughout|around)\s+(the world|europe|asia|africa|america|the globe)\b",
    r"\b(from .+ to .+ to)\b",  # "from X to Y to Z"
    r"\b(\w+,\s+\w+,\s+and\s+\w+)\b",  # "X, Y, and Z" pattern
]


def _srt_time_to_seconds(tc: str) -> float:
    """Convert SRT timecode to seconds."""
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", tc)
    if not m:
        return 0.0
    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mi * 60 + s + ms / 1000.0


def detect_density_montages(
    entities: Dict[str, Dict],
    window_seconds: float = 8.0,
    min_entities: int = 3,
) -> List[MontageOpportunity]:
    """
    Detect montage opportunities from entity density.

    When multiple entities are mentioned within a short time window,
    this suggests a montage/collage could be effective.
    """
    # Collect all occurrences with their timecodes
    occurrences = []
    for entity_name, entity_data in entities.items():
        entity_type = entity_data.get("entity_type", "unknown")
        for occ in entity_data.get("occurrences", []):
            tc = occ.get("timecode", "00:00:00,000")
            occurrences.append({
                "entity": entity_name,
                "entity_type": entity_type,
                "timecode": tc,
                "seconds": _srt_time_to_seconds(tc),
                "cue_idx": occ.get("cue_idx", 0),
            })

    # Sort by time
    occurrences.sort(key=lambda x: x["seconds"])

    # Sliding window to find dense clusters
    montages = []
    montage_count = 0
    i = 0
    used_cues: Set[int] = set()

    while i < len(occurrences):
        window_start = occurrences[i]["seconds"]
        window_entities = []

        # Collect entities within window
        j = i
        while j < len(occurrences) and occurrences[j]["seconds"] - window_start <= window_seconds:
            window_entities.append(occurrences[j])
            j += 1

        # Check if we have enough unique entities
        unique_entities = list(set(e["entity"] for e in window_entities))

        if len(unique_entities) >= min_entities:
            # Check if we've already flagged this area
            cue_idxs = set(e["cue_idx"] for e in window_entities)
            if not cue_idxs & used_cues:
                montage_count += 1
                first_occ = window_entities[0]

                montages.append(MontageOpportunity(
                    montage_id=f"density_{montage_count:03d}",
                    montage_type="density",
                    timecode=first_occ["timecode"],
                    cue_idx=first_occ["cue_idx"],
                    entities=unique_entities,
                    reason=f"{len(unique_entities)} entities mentioned within {window_seconds}s",
                    suggested_image_count=min(len(unique_entities), 5),
                ))
                used_cues.update(cue_idxs)

        i += 1

    return montages


def detect_sweep_event_montages(
    entities: Dict[str, Dict],
) -> List[MontageOpportunity]:
    """
    Detect montage opportunities from sweep events.

    Events like "French Revolution" or "World War II" have extensive
    imagery available and benefit from montage treatment.
    """
    montages = []
    montage_count = 0

    for entity_name, entity_data in entities.items():
        entity_lower = entity_name.lower()

        # Check if this is a sweep event
        is_sweep = False
        matched_sweep = None
        for sweep in SWEEP_EVENTS:
            if sweep in entity_lower or entity_lower in sweep:
                is_sweep = True
                matched_sweep = sweep
                break

        if is_sweep:
            # Get first occurrence
            occs = entity_data.get("occurrences", [])
            if occs:
                first_occ = occs[0]
                montage_count += 1

                montages.append(MontageOpportunity(
                    montage_id=f"sweep_{montage_count:03d}",
                    montage_type="sweep_event",
                    timecode=first_occ.get("timecode", "00:00:00,000"),
                    cue_idx=first_occ.get("cue_idx", 0),
                    entities=[entity_name],
                    reason=f"Sweep event '{entity_name}' has extensive imagery",
                    suggested_image_count=4,
                ))

    return montages


def detect_enumeration_montages_from_srt(
    srt_path: str,
    entities: Dict[str, Dict],
) -> List[MontageOpportunity]:
    """
    Detect montage opportunities from enumeration language in transcript.

    Patterns like "leaders like Washington, Jefferson, and Adams" or
    "many countries including..." suggest montage treatment.
    """
    # Parse SRT to get cue texts
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    cues = []

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) >= 2 and re.match(r"^\d+$", lines[0]):
            time_match = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})", lines[1])
            if time_match:
                text = " ".join(lines[2:])
                cues.append({
                    "index": int(lines[0]),
                    "timecode": time_match.group(1).replace(".", ","),
                    "text": text,
                })

    # Compile patterns
    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in ENUMERATION_PATTERNS]

    montages = []
    montage_count = 0

    for cue in cues:
        text = cue["text"]

        for pattern in compiled_patterns:
            if pattern.search(text):
                # Find entities mentioned in this cue
                mentioned_entities = []
                for entity_name, entity_data in entities.items():
                    for occ in entity_data.get("occurrences", []):
                        if occ.get("cue_idx") == cue["index"]:
                            mentioned_entities.append(entity_name)
                            break

                if mentioned_entities:
                    montage_count += 1
                    montages.append(MontageOpportunity(
                        montage_id=f"enum_{montage_count:03d}",
                        montage_type="enumeration",
                        timecode=cue["timecode"],
                        cue_idx=cue["index"],
                        entities=mentioned_entities,
                        reason="Enumeration language detected",
                        suggested_image_count=min(len(mentioned_entities) + 1, 5),
                        source_text=text[:200],
                    ))
                break  # One match per cue is enough

    return montages


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect montage/collage opportunities from entities"
    )
    parser.add_argument(
        "--entities",
        help="Path to entities_map.json from srt_entities.py",
    )
    parser.add_argument(
        "--srt",
        help="Path to original SRT (for enumeration detection)",
    )
    parser.add_argument(
        "--out",
        help="Output JSON path (default: same directory as input with _montages.json suffix)",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=8.0,
        help="Time window in seconds for density detection (default: 8.0)",
    )
    parser.add_argument(
        "--min-entities",
        type=int,
        default=3,
        help="Minimum entities for density montage (default: 3)",
    )
    args = parser.parse_args(argv)

    if not args.entities and not args.srt:
        print("Error: Must provide --entities or --srt", file=sys.stderr)
        return 1

    # Load entities
    if args.entities:
        with open(args.entities, "r", encoding="utf-8") as f:
            data = json.load(f)
        entities = data.get("entities", {})
        source_srt = data.get("source_srt")
    else:
        print("Standalone SRT mode not yet implemented - use --entities", file=sys.stderr)
        return 1

    # Default output path
    if not args.out:
        input_path = Path(args.entities or args.srt)
        args.out = str(input_path.parent / f"{input_path.stem}_montages.json")

    print(f"Analyzing {len(entities)} entities for montage opportunities...")

    # Detect different types of montages
    all_montages = []

    # 1. Density-based montages
    density_montages = detect_density_montages(
        entities,
        window_seconds=args.window,
        min_entities=args.min_entities,
    )
    all_montages.extend(density_montages)
    print(f"  Found {len(density_montages)} density-based montage opportunities")

    # 2. Sweep event montages
    sweep_montages = detect_sweep_event_montages(entities)
    all_montages.extend(sweep_montages)
    print(f"  Found {len(sweep_montages)} sweep event montages")

    # 3. Enumeration montages (if SRT available)
    srt_path = args.srt or source_srt
    if srt_path and os.path.exists(srt_path):
        enum_montages = detect_enumeration_montages_from_srt(srt_path, entities)
        all_montages.extend(enum_montages)
        print(f"  Found {len(enum_montages)} enumeration-based montages")

    # Sort by timecode
    all_montages.sort(key=lambda m: _srt_time_to_seconds(m.timecode))

    # Convert to dict for JSON output
    output = {
        "montage_opportunities": [
            {
                "montage_id": m.montage_id,
                "montage_type": m.montage_type,
                "timecode": m.timecode,
                "cue_idx": m.cue_idx,
                "entities": m.entities,
                "reason": m.reason,
                "suggested_image_count": m.suggested_image_count,
                "source_text": m.source_text,
            }
            for m in all_montages
        ],
        "source_entities": args.entities,
        "summary": {
            "total_montages": len(all_montages),
            "density_montages": len(density_montages),
            "sweep_montages": len(sweep_montages),
            "enumeration_montages": len(all_montages) - len(density_montages) - len(sweep_montages),
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.out}")
    print(f"  Total montage opportunities: {len(all_montages)}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
