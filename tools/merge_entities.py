#!/usr/bin/env python3
"""
merge_entities.py

Merge duplicate entities identified by transcript summary clusters
or fuzzy matching. Produces merged_entities.json for downstream steps.

Merge strategy:
- Pick canonical name (first in cluster that exists in entity map)
- Combine occurrences (deduplicated by timecode)
- Union aliases
- Take max priority
- Concatenate contexts
- Record merged_from for audit trail

Usage:
    python tools/merge_entities.py \\
        --map enriched_entities.json --out merged_entities.json

    # With transcript summary clusters:
    python tools/merge_entities.py \\
        --map enriched_entities.json --summary transcript_summary.json

    # Fuzzy-only (no summary):
    python tools/merge_entities.py \\
        --map enriched_entities.json --fuzzy-threshold 0.85
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def find_entity_key(entities: dict, name: str) -> Optional[str]:
    """Find entity key matching a name (case-insensitive)."""
    if name in entities:
        return name
    name_lower = name.lower()
    for key in entities:
        if key.lower() == name_lower:
            return key
    return None


def deduplicate_occurrences(occurrences: list) -> list:
    """Deduplicate occurrences by timecode, keeping earliest."""
    seen = set()
    result = []
    for occ in occurrences:
        tc = occ.get("timecode", "")
        if tc and tc not in seen:
            seen.add(tc)
            result.append(occ)
        elif not tc:
            result.append(occ)
    result.sort(key=lambda o: o.get("timecode", ""))
    return result


def merge_entity_clusters(
    entities_map: dict,
    clusters: List[List[str]],
) -> Tuple[dict, List[dict]]:
    """Merge entity clusters into canonical entities.

    Args:
        entities_map: Full map with 'entities' key.
        clusters: List of name clusters (canonical first).

    Returns:
        Tuple of (updated entities_map, list of merge audit records).
    """
    entities = entities_map.get("entities", {})
    audit = []

    for cluster in clusters:
        if len(cluster) < 2:
            continue

        # Find which cluster members exist in entity map
        existing = []
        for name in cluster:
            key = find_entity_key(entities, name)
            if key:
                existing.append(key)

        if len(existing) < 2:
            continue

        # Pick canonical: first existing member in the cluster order
        canonical = existing[0]
        to_merge = existing[1:]

        canonical_data = entities[canonical]

        merged_from = []
        for merge_key in to_merge:
            merge_data = entities[merge_key]
            merged_from.append(merge_key)

            # Combine occurrences
            existing_occs = canonical_data.get("occurrences", [])
            merge_occs = merge_data.get("occurrences", [])
            canonical_data["occurrences"] = deduplicate_occurrences(
                existing_occs + merge_occs
            )

            # Union aliases
            existing_aliases = set(canonical_data.get("aliases", []))
            merge_aliases = set(merge_data.get("aliases", []))
            existing_aliases.add(merge_key)  # Add merged name as alias
            existing_aliases.update(merge_aliases)
            canonical_data["aliases"] = sorted(existing_aliases)

            # Take max priority
            canonical_data["priority"] = max(
                canonical_data.get("priority", 0.0),
                merge_data.get("priority", 0.0),
            )

            # Concatenate contexts (if different)
            ctx1 = canonical_data.get("context", "")
            ctx2 = merge_data.get("context", "")
            if ctx2 and ctx2 not in ctx1:
                canonical_data["context"] = f"{ctx1} | {ctx2}" if ctx1 else ctx2

            # Remove merged entity
            del entities[merge_key]

        if merged_from:
            canonical_data["merged_from"] = merged_from
            audit.append({
                "canonical": canonical,
                "merged": merged_from,
                "total_occurrences": len(canonical_data.get("occurrences", [])),
            })

    return entities_map, audit


def find_fuzzy_clusters(
    entities: dict,
    threshold: float = 0.85,
) -> List[List[str]]:
    """Find entity clusters using fuzzy matching.

    Only compares entities of the same type. Uses both:
    - Substring containment (e.g. "Pandey" in "Mangal Pandey")
    - Similarity ratio >= threshold

    Args:
        entities: Dict of entity_name -> payload.
        threshold: Minimum similarity ratio for matching.

    Returns:
        List of name clusters (canonical/longer name first).
    """
    # Group by entity type
    by_type: Dict[str, List[str]] = {}
    for name, data in entities.items():
        etype = data.get("entity_type", "unknown").lower()
        by_type.setdefault(etype, []).append(name)

    clusters: List[List[str]] = []
    already_clustered: Set[str] = set()

    for etype, names in by_type.items():
        for i, name_a in enumerate(names):
            if name_a in already_clustered:
                continue

            cluster = [name_a]
            a_lower = name_a.lower()

            for j, name_b in enumerate(names):
                if i == j or name_b in already_clustered:
                    continue

                b_lower = name_b.lower()

                # Substring containment
                if a_lower in b_lower or b_lower in a_lower:
                    cluster.append(name_b)
                    already_clustered.add(name_b)
                    continue

                # Similarity ratio
                ratio = difflib.SequenceMatcher(None, a_lower, b_lower).ratio()
                if ratio >= threshold:
                    cluster.append(name_b)
                    already_clustered.add(name_b)

            if len(cluster) >= 2:
                # Sort by name length descending (longest = most specific = canonical)
                cluster.sort(key=lambda n: -len(n))
                clusters.append(cluster)
                already_clustered.add(name_a)

    return clusters


# =============================================================================
# CLI
# =============================================================================


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge duplicate entities (from summary clusters or fuzzy matching)"
    )
    parser.add_argument(
        "--map", required=True,
        help="Path to enriched_entities.json"
    )
    parser.add_argument(
        "--summary",
        help="Path to transcript_summary.json (for entity_clusters)"
    )
    parser.add_argument(
        "--out",
        help="Output path (default: merged_entities.json in same dir as --map)"
    )
    parser.add_argument(
        "--fuzzy-threshold", type=float, default=0.85,
        help="Similarity threshold for fuzzy fallback (default: 0.85)"
    )
    parser.add_argument(
        "--no-fuzzy", action="store_true",
        help="Disable fuzzy matching (only use summary clusters)"
    )
    args = parser.parse_args(argv)

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities file not found: {map_path}", file=sys.stderr)
        return 1

    # Load entities
    with open(map_path, "r", encoding="utf-8") as f:
        entities_map = json.load(f)

    entities = entities_map.get("entities", {})
    if not entities:
        print("Warning: No entities found", file=sys.stderr)
        return 1

    original_count = len(entities)

    # Load clusters from summary
    clusters = []
    summary_path = args.summary
    if not summary_path:
        # Auto-detect in same directory
        candidate = map_path.parent / "transcript_summary.json"
        if candidate.exists():
            summary_path = str(candidate)

    if summary_path and Path(summary_path).exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        clusters = summary.get("entity_clusters", [])
        print(f"Loaded {len(clusters)} clusters from summary")

    # Apply summary clusters
    audit = []
    if clusters:
        entities_map, audit = merge_entity_clusters(entities_map, clusters)
        print(f"Summary-based merges: {len(audit)}")
        for record in audit:
            print(f"  {record['canonical']} <- {', '.join(record['merged'])} "
                  f"({record['total_occurrences']} occurrences)")

    # Fuzzy fallback
    if not args.no_fuzzy:
        entities = entities_map.get("entities", {})
        fuzzy_clusters = find_fuzzy_clusters(entities, threshold=args.fuzzy_threshold)

        if fuzzy_clusters:
            print(f"\nFuzzy clusters found: {len(fuzzy_clusters)}")
            entities_map, fuzzy_audit = merge_entity_clusters(entities_map, fuzzy_clusters)
            audit.extend(fuzzy_audit)
            for record in fuzzy_audit:
                print(f"  {record['canonical']} <- {', '.join(record['merged'])} "
                      f"({record['total_occurrences']} occurrences)")

    final_count = len(entities_map.get("entities", {}))
    merged_count = original_count - final_count

    # Determine output path
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = map_path.parent / "merged_entities.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)

    print(f"\nMerge Summary:")
    print(f"  Original entities: {original_count}")
    print(f"  After merge: {final_count}")
    print(f"  Entities merged: {merged_count}")
    print(f"\nOutput: {out_path}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
