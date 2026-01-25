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
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re


# Thread-safe print
_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with _print_lock:
        print(*args, **kwargs)


def safe_folder_name(name: str) -> str:
    import re
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    return name or "untitled"


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
) -> Tuple[str, bool, Path]:
    """
    Download images for a single entity. Returns (entity_name, success, entity_dir).
    Thread-safe: only uses safe_print for output.
    """
    entity_dir = out_dir / safe_folder_name(entity_name)
    
    # If the entity output directory already exists, skip the download step
    if entity_dir.exists():
        safe_print(f"[{current_idx}/{total_entities}] Skipping: {entity_name} (already downloaded)")
        return (entity_name, True, entity_dir)
    
    safe_print(f"[{current_idx}/{total_entities}] Downloading: {entity_name}")
    
    try:
        cmd = [
            sys.executable,
            str(downloader),
            entity_name,
            "--limit",
            str(images_per_entity),
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
        safe_print(f"[{current_idx}/{total_entities}] Done: {entity_name}")
        return (entity_name, True, entity_dir)
    except subprocess.CalledProcessError as e:
        safe_print(f"[{current_idx}/{total_entities}] Failed: {entity_name} - {e}", file=sys.stderr)
        return (entity_name, False, entity_dir)


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
    parser = argparse.ArgumentParser(description="Download images for entities and update entities_map.json")
    parser.add_argument("--map", required=True, help="Path to entities_map.json produced by srt_entities.py")
    parser.add_argument("--images-per-entity", type=int, default=3, help="Max images per entity (default: 3)")
    parser.add_argument("--user-agent", type=str, default="b-roll-pipeline/0.1", help="HTTP User-Agent for downloader")
    parser.add_argument("--png-width", type=int, default=3000, help="PNG width for SVG conversion (default: 3000)")
    parser.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion")
    parser.add_argument("--delay", type=float, default=0.1, help="Politeness delay between requests (seconds, default: 0.1)")
    parser.add_argument("-j", "--parallel", type=int, default=1, 
                        help="Number of parallel downloads (default: 1, recommended: 4)")
    args = parser.parse_args(argv)

    with open(args.map, "r", encoding="utf-8") as f:
        entities_map = json.load(f)
    entities: Dict[str, Dict] = entities_map.get("entities", {})
    if not entities:
        print("No entities in map.", file=sys.stderr)
        return 2

    out_dir = resolve_output_dir()
    downloader = Path(__file__).resolve().parents[1] / "wikipedia_image_downloader.py"
    if not downloader.exists():
        print("wikipedia_image_downloader.py not found.", file=sys.stderr)
        return 2

    # Filter to entities that need downloading
    to_download = [
        (name, payload) for name, payload in entities.items()
        if not payload.get("images")
    ]
    
    if not to_download:
        print("All entities already have images. Nothing to download.")
        return 0
    
    total = len(to_download)
    workers = max(1, min(args.parallel, total))  # Don't use more workers than entities
    
    print(f"Downloading images for {total} entities using {workers} parallel worker(s)...")
    print(f"Delay between requests: {args.delay}s")
    print()
    
    # Track results: entity_name -> (success, entity_dir)
    results: Dict[str, Tuple[bool, Path]] = {}
    
    if workers == 1:
        # Sequential mode (original behavior, slightly optimized)
        for idx, (entity_name, payload) in enumerate(to_download, start=1):
            entity_type = payload.get("entity_type", "")
            name, success, entity_dir = download_entity(
                entity_name=entity_name,
                entity_type=entity_type,
                out_dir=out_dir,
                downloader=downloader,
                images_per_entity=args.images_per_entity,
                user_agent=args.user_agent,
                png_width=args.png_width,
                delay=args.delay,
                no_svg_to_png=args.no_svg_to_png,
                worker_id=0,
                total_entities=total,
                current_idx=idx,
            )
            results[name] = (success, entity_dir)
    else:
        # Parallel mode using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for idx, (entity_name, payload) in enumerate(to_download, start=1):
                entity_type = payload.get("entity_type", "")
                future = executor.submit(
                    download_entity,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    out_dir=out_dir,
                    downloader=downloader,
                    images_per_entity=args.images_per_entity,
                    user_agent=args.user_agent,
                    png_width=args.png_width,
                    delay=args.delay,
                    no_svg_to_png=args.no_svg_to_png,
                    worker_id=idx % workers,
                    total_entities=total,
                    current_idx=idx,
                )
                futures[future] = entity_name
            
            # Collect results as they complete
            for future in as_completed(futures):
                entity_name = futures[future]
                try:
                    name, success, entity_dir = future.result()
                    results[name] = (success, entity_dir)
                except Exception as e:
                    print(f"Error processing {entity_name}: {e}", file=sys.stderr)
                    results[entity_name] = (False, out_dir / safe_folder_name(entity_name))
    
    # Harvest results and update entities map
    print()
    print("Harvesting downloaded images...")
    
    success_count = 0
    fail_count = 0
    
    for entity_name, payload in entities.items():
        if entity_name not in results:
            continue  # Already had images
        
        success, entity_dir = results[entity_name]
        if not success:
            fail_count += 1
            continue
        
        images = harvest_images(entity_dir)
        if images:
            payload["images"] = images
            success_count += 1
        else:
            # Download succeeded but no images found (e.g., no Wikipedia page)
            fail_count += 1

    # Write updated map
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)
    
    print()
    print(f"Updated {args.map}")
    print(f"  Success: {success_count} entities")
    print(f"  Failed:  {fail_count} entities")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
