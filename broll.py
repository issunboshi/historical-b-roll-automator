#!/usr/bin/env python3
"""
broll.py - Unified CLI for the B-Roll Finder pipeline.

This script orchestrates the full B-roll generation workflow:
  1. Extract entities from an SRT transcript (via LLM)
  2. Enrich entities with priority scores and transcript context
  3. Generate LLM-powered Wikipedia search strategies
  4. Download images from Wikipedia for each entity
  5. Generate FCP XML for import into DaVinci Resolve

Usage:
  # Full pipeline (most common)
  python broll.py pipeline --srt video.srt --output-dir ./output --fps 24

  # Individual steps
  python broll.py extract --srt video.srt --output entities_map.json
  python broll.py enrich --map entities_map.json --srt video.srt
  python broll.py strategies --map enriched_entities.json
  python broll.py download --map strategies_entities.json
  python broll.py xml --map strategies_entities.json --output timeline.xml

Config:
  Options can be set in broll_config.yaml or via CLI flags.
  CLI flags override config file values.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Optional YAML support for config
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


DEFAULT_CONFIG = {
    "images_per_entity": 3,
    "image_duration_seconds": 4.0,
    "min_gap_seconds": 2.0,
    "broll_track_count": 4,
    "allow_non_pd": False,
    "fps": 25.0,
    "llm": {
        "provider": "openai",
        "model": "gpt-4o-mini",
    },
}


def find_config_file() -> Optional[Path]:
    """Look for broll_config.yaml in current dir or script dir."""
    candidates = [
        Path.cwd() / "broll_config.yaml",
        Path(__file__).parent / "broll_config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config from YAML file, falling back to defaults."""
    config = dict(DEFAULT_CONFIG)
    
    path = config_path or find_config_file()
    if path and path.exists():
        if not YAML_AVAILABLE:
            print(f"Warning: Found {path} but PyYAML not installed. Using defaults.", file=sys.stderr)
            return config
        try:
            with open(path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            # Merge file config into defaults
            for key, value in file_config.items():
                if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                    config[key].update(value)
                else:
                    config[key] = value
        except Exception as e:
            print(f"Warning: Failed to load config from {path}: {e}", file=sys.stderr)
    
    return config


def resolve_script_path(script_name: str) -> Path:
    """Resolve path to a script relative to this file's location."""
    base = Path(__file__).parent
    # Check tools/ subdirectory first
    tools_path = base / "tools" / script_name
    if tools_path.exists():
        return tools_path
    # Check root directory
    root_path = base / script_name
    if root_path.exists():
        return root_path
    raise FileNotFoundError(f"Script not found: {script_name}")


def run_step(
    description: str,
    cmd: List[str],
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run a subprocess step with nice output."""
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"{'='*60}")
    print(f"Running: {' '.join(cmd[:3])}...")
    print()
    
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True if capture_output else None,
    )
    
    if result.returncode != 0 and not check:
        print(f"Warning: Step exited with code {result.returncode}", file=sys.stderr)
    
    return result


def cmd_extract(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run entity extraction from SRT."""
    script = resolve_script_path("srt_entities.py")
    
    # Determine output path
    if args.output:
        out_path = Path(args.output)
    elif args.output_dir:
        out_path = Path(args.output_dir) / "entities_map.json"
    else:
        out_path = Path("entities_map.json")
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build command
    llm_config = config.get("llm", {})
    provider = args.provider or llm_config.get("provider", "openai")
    model = args.model or llm_config.get("model", "gpt-4o-mini")
    fps = args.fps or config.get("fps", 25.0)
    
    cmd = [
        sys.executable, str(script),
        "--srt", str(args.srt),
        "--out", str(out_path),
        "--provider", provider,
        "--model", model,
        "--fps", str(fps),
    ]
    
    if args.subject:
        cmd.extend(["--subject", args.subject])
    
    if args.delay:
        cmd.extend(["--delay", str(args.delay)])
    
    try:
        run_step("Extracting entities from transcript", cmd)
        print(f"\nEntities saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Entity extraction failed: {e}", file=sys.stderr)
        return 1


def cmd_download(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run image download for entities."""
    script = resolve_script_path("download_entities.py")
    
    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
        return 1
    
    images_per_entity = args.images_per_entity or config.get("images_per_entity", 3)
    parallel = getattr(args, 'parallel', None) or config.get("parallel_downloads", 4)
    
    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--images-per-entity", str(images_per_entity),
        "--parallel", str(parallel),
    ]
    
    if args.delay:
        cmd.extend(["--delay", str(args.delay)])
    
    if args.no_svg_to_png:
        cmd.append("--no-svg-to-png")
    
    try:
        run_step("Downloading images from Wikipedia", cmd)
        print(f"\nEntities map updated: {map_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Image download failed: {e}", file=sys.stderr)
        return 1


def cmd_enrich(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run entity enrichment to add priority scores and context."""
    script = resolve_script_path("enrich_entities.py")

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
        return 1

    srt_path = Path(args.srt)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = map_path.parent / "enriched_entities.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--srt", str(srt_path),
        "--out", str(out_path),
    ]

    try:
        run_step("Enriching entities with priority and context", cmd)
        print(f"\nEnriched entities saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Entity enrichment failed: {e}", file=sys.stderr)
        return 1


def cmd_strategies(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Generate LLM-powered Wikipedia search strategies."""
    script = resolve_script_path("generate_search_strategies.py")

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: enriched_entities map not found: {map_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = map_path.parent / "strategies_entities.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--out", str(out_path),
    ]

    if args.video_context:
        cmd.extend(["--video-context", args.video_context])

    if args.batch_size:
        cmd.extend(["--batch-size", str(args.batch_size)])

    if args.cache_dir:
        cmd.extend(["--cache-dir", args.cache_dir])

    try:
        run_step("Generating search strategies", cmd)
        print(f"\nSearch strategies saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Search strategy generation failed: {e}", file=sys.stderr)
        return 1


def cmd_xml(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Generate FCP XML from entities map."""
    script = resolve_script_path("generate_broll_xml.py")
    
    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
        return 1
    
    # Determine output path
    if args.output:
        out_path = Path(args.output)
    elif args.output_dir:
        out_path = Path(args.output_dir) / "broll_timeline.xml"
    else:
        out_path = Path("broll_timeline.xml")
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    fps = args.fps or config.get("fps", 25.0)
    duration = args.duration or config.get("image_duration_seconds", 4.0)
    gap = args.gap or config.get("min_gap_seconds", 2.0)
    tracks = args.tracks or config.get("broll_track_count", 4)
    allow_non_pd = args.allow_non_pd or config.get("allow_non_pd", False)
    timeline_name = args.timeline_name or config.get("timeline_name", "B-Roll Timeline")
    
    cmd = [
        sys.executable, str(script),
        str(map_path),
        "--output", str(out_path),
        "--fps", str(fps),
        "--duration", str(duration),
        "--gap", str(gap),
        "--tracks", str(tracks),
        "--timeline-name", timeline_name,
    ]
    
    if allow_non_pd:
        cmd.append("--allow-non-pd")
    
    try:
        run_step("Generating FCP XML timeline", cmd)
        print(f"\nXML saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"XML generation failed: {e}", file=sys.stderr)
        return 1


def cmd_pipeline(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run the full pipeline: extract -> enrich -> strategies -> download -> xml."""
    # Validate required inputs
    if not args.srt:
        print("Error: --srt is required for pipeline command", file=sys.stderr)
        return 1

    srt_path = Path(args.srt)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    # Set up output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Use SRT filename as output directory name
        output_dir = Path.cwd() / srt_path.stem

    output_dir.mkdir(parents=True, exist_ok=True)

    # Define intermediate file paths
    entities_path = output_dir / "entities_map.json"
    enriched_entities_path = output_dir / "enriched_entities.json"
    strategies_entities_path = output_dir / "strategies_entities.json"
    xml_path = output_dir / "broll_timeline.xml"
    
    print(f"\n{'#'*60}")
    print(f"# B-Roll Pipeline")
    print(f"#")
    print(f"# Input:  {srt_path}")
    print(f"# Output: {output_dir}")
    print(f"{'#'*60}")
    
    # Step 1: Extract entities
    extract_args = argparse.Namespace(
        srt=str(srt_path),
        output=str(entities_path),
        output_dir=None,
        provider=args.provider,
        model=args.model,
        fps=args.fps,
        subject=args.subject,
        delay=args.extract_delay,
    )
    
    result = cmd_extract(extract_args, config)
    if result != 0:
        print("\nPipeline failed at: entity extraction", file=sys.stderr)
        return result

    # Step 2: Enrich entities
    enrich_args = argparse.Namespace(
        map=str(entities_path),
        srt=str(srt_path),
        output=str(enriched_entities_path),
    )

    result = cmd_enrich(enrich_args, config)
    if result != 0:
        print("\nPipeline failed at: entity enrichment", file=sys.stderr)
        return result

    # Step 3: Generate search strategies
    strategies_args = argparse.Namespace(
        map=str(enriched_entities_path),
        output=str(strategies_entities_path),
        video_context=args.subject,  # Use --subject as video context
        batch_size=getattr(args, 'batch_size', None),
        cache_dir=getattr(args, 'cache_dir', None),
    )

    result = cmd_strategies(strategies_args, config)
    if result != 0:
        print("\nPipeline failed at: search strategy generation", file=sys.stderr)
        return result

    # Step 4: Download images
    download_args = argparse.Namespace(
        map=str(strategies_entities_path),
        images_per_entity=args.images_per_entity,
        delay=args.download_delay,
        parallel=args.parallel,
        no_svg_to_png=args.no_svg_to_png,
    )

    result = cmd_download(download_args, config)
    if result != 0:
        print("\nPipeline failed at: image download", file=sys.stderr)
        return result

    # Step 5: Generate XML
    xml_args = argparse.Namespace(
        map=str(strategies_entities_path),
        output=str(xml_path),
        output_dir=None,
        fps=args.fps,
        duration=args.duration,
        gap=args.gap,
        tracks=args.tracks,
        allow_non_pd=args.allow_non_pd,
        timeline_name=args.timeline_name,
    )
    
    result = cmd_xml(xml_args, config)
    if result != 0:
        print("\nPipeline failed at: XML generation", file=sys.stderr)
        return result
    
    # Success summary
    print(f"\n{'#'*60}")
    print(f"# Pipeline Complete!")
    print(f"#")
    print(f"# Output files:")
    print(f"#   - Entities:   {entities_path}")
    print(f"#   - Enriched:   {enriched_entities_path}")
    print(f"#   - Strategies: {strategies_entities_path}")
    print(f"#   - XML:        {xml_path}")
    print(f"#")
    print(f"# Next steps:")
    print(f"#   1. Open DaVinci Resolve")
    print(f"#   2. File > Import > Timeline...")
    print(f"#   3. Select: {xml_path}")
    print(f"{'#'*60}")

    return 0


def cmd_status(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Show current configuration and check script availability."""
    print("B-Roll Pipeline Status")
    print("=" * 40)
    
    # Config info
    config_path = find_config_file()
    if config_path:
        print(f"Config file: {config_path}")
    else:
        print("Config file: (not found, using defaults)")
    
    print()
    print("Configuration:")
    print(f"  LLM Provider:     {config.get('llm', {}).get('provider', 'openai')}")
    print(f"  LLM Model:        {config.get('llm', {}).get('model', 'gpt-4o-mini')}")
    print(f"  FPS:              {config.get('fps', 25.0)}")
    print(f"  Images/entity:    {config.get('images_per_entity', 3)}")
    print(f"  Clip duration:    {config.get('image_duration_seconds', 4.0)}s")
    print(f"  Min gap:          {config.get('min_gap_seconds', 2.0)}s")
    print(f"  B-roll tracks:    {config.get('broll_track_count', 4)}")
    print(f"  Allow non-PD:     {config.get('allow_non_pd', False)}")
    
    print()
    print("Scripts:")

    scripts = [
        ("srt_entities.py", "Entity extraction"),
        ("enrich_entities.py", "Entity enrichment"),
        ("generate_search_strategies.py", "Search strategy generation"),
        ("download_entities.py", "Image download"),
        ("generate_broll_xml.py", "XML generation"),
        ("wikipedia_image_downloader.py", "Wikipedia downloader"),
    ]
    
    for script_name, description in scripts:
        try:
            path = resolve_script_path(script_name)
            print(f"  [OK] {description}: {path}")
        except FileNotFoundError:
            print(f"  [MISSING] {description}: {script_name}")
    
    print()
    print("Environment:")
    if os.environ.get("OPENAI_API_KEY"):
        print("  [OK] OPENAI_API_KEY is set")
    else:
        print("  [WARN] OPENAI_API_KEY not set (required for OpenAI provider)")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("  [OK] ANTHROPIC_API_KEY is set")
    else:
        print("  [WARN] ANTHROPIC_API_KEY not set (required for search strategies)")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="B-Roll Finder - Unified pipeline for generating B-roll from transcripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline
  %(prog)s pipeline --srt video.srt --fps 24

  # Run with custom output directory
  %(prog)s pipeline --srt video.srt --output-dir ./my-project

  # Individual steps
  %(prog)s extract --srt video.srt --output entities.json
  %(prog)s download --map entities.json
  %(prog)s xml --map entities.json --output timeline.xml

  # Check configuration
  %(prog)s status
        """,
    )
    
    parser.add_argument(
        "--config", "-c",
        type=Path,
        help="Path to config file (default: broll_config.yaml)",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Pipeline command (full workflow)
    p_pipeline = subparsers.add_parser(
        "pipeline",
        help="Run the full pipeline: extract -> enrich -> strategies -> download -> xml",
    )
    p_pipeline.add_argument("--srt", required=True, help="Path to SRT transcript")
    p_pipeline.add_argument("--output-dir", "-o", help="Output directory (default: SRT filename)")
    p_pipeline.add_argument("--fps", type=float, help="Timeline frame rate")
    p_pipeline.add_argument("--subject", help="Transcript subject for entity context")
    p_pipeline.add_argument("--provider", choices=["openai", "ollama"], help="LLM provider")
    p_pipeline.add_argument("--model", help="LLM model name")
    p_pipeline.add_argument("--images-per-entity", type=int, help="Max images per entity")
    p_pipeline.add_argument("--duration", "-d", type=float, help="Clip duration in seconds")
    p_pipeline.add_argument("--gap", "-g", type=float, help="Min gap between clips in seconds")
    p_pipeline.add_argument("--tracks", "-t", type=int, help="Number of B-roll tracks")
    p_pipeline.add_argument("--allow-non-pd", action="store_true", help="Include non-public-domain images")
    p_pipeline.add_argument("--timeline-name", help="Name for the timeline")
    p_pipeline.add_argument("--extract-delay", type=float, default=0.2, help="Delay between LLM calls")
    p_pipeline.add_argument("--download-delay", type=float, default=0.1, help="Delay between download requests")
    p_pipeline.add_argument("-j", "--parallel", type=int, default=4,
                            help="Number of parallel downloads (default: 4)")
    p_pipeline.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion")
    p_pipeline.add_argument("--batch-size", type=int, help="Entities per LLM call (5-10)")
    p_pipeline.add_argument("--cache-dir", help="Wikipedia cache directory")
    
    # Extract command
    p_extract = subparsers.add_parser(
        "extract",
        help="Extract entities from SRT transcript",
    )
    p_extract.add_argument("--srt", required=True, help="Path to SRT transcript")
    p_extract.add_argument("--output", "-o", help="Output JSON path")
    p_extract.add_argument("--output-dir", help="Output directory (creates entities_map.json inside)")
    p_extract.add_argument("--fps", type=float, help="FPS for timecode conversion")
    p_extract.add_argument("--subject", help="Transcript subject for entity context")
    p_extract.add_argument("--provider", choices=["openai", "ollama"], help="LLM provider")
    p_extract.add_argument("--model", help="LLM model name")
    p_extract.add_argument("--delay", type=float, help="Delay between LLM calls")
    
    # Download command
    p_download = subparsers.add_parser(
        "download",
        help="Download images for entities",
    )
    p_download.add_argument("--map", required=True, help="Path to entities_map.json")
    p_download.add_argument("--images-per-entity", type=int, help="Max images per entity")
    p_download.add_argument("--delay", type=float, help="Delay between requests (default: 0.1s)")
    p_download.add_argument("-j", "--parallel", type=int, default=4,
                            help="Number of parallel downloads (default: 4)")
    p_download.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion")

    # Enrich command
    p_enrich = subparsers.add_parser(
        "enrich",
        help="Enrich entities with priority scores and transcript context",
    )
    p_enrich.add_argument("--map", required=True, help="Path to entities_map.json")
    p_enrich.add_argument("--srt", required=True, help="Path to original SRT file")
    p_enrich.add_argument("--output", "-o", help="Output JSON path (default: enriched_entities.json)")

    # Strategies command
    p_strategies = subparsers.add_parser(
        "strategies",
        help="Generate LLM-powered Wikipedia search strategies",
    )
    p_strategies.add_argument("--map", required=True, help="Path to enriched_entities.json")
    p_strategies.add_argument("--output", "-o", help="Output JSON path")
    p_strategies.add_argument("--video-context", help="Video topic/title for disambiguation")
    p_strategies.add_argument("--batch-size", type=int, help="Entities per LLM call (5-10)")
    p_strategies.add_argument("--cache-dir", help="Wikipedia validation cache directory")

    # XML command
    p_xml = subparsers.add_parser(
        "xml",
        help="Generate FCP XML from entities map",
    )
    p_xml.add_argument("--map", required=True, help="Path to entities_map.json")
    p_xml.add_argument("--output", "-o", help="Output XML path")
    p_xml.add_argument("--output-dir", help="Output directory")
    p_xml.add_argument("--fps", type=float, help="Timeline frame rate")
    p_xml.add_argument("--duration", "-d", type=float, help="Clip duration in seconds")
    p_xml.add_argument("--gap", "-g", type=float, help="Min gap between clips")
    p_xml.add_argument("--tracks", "-t", type=int, help="Number of B-roll tracks")
    p_xml.add_argument("--allow-non-pd", action="store_true", help="Include non-public-domain images")
    p_xml.add_argument("--timeline-name", help="Name for the timeline")
    
    # Status command
    subparsers.add_parser(
        "status",
        help="Show configuration and check script availability",
    )
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 0
    
    # Load configuration
    config = load_config(args.config)
    
    # Dispatch to command handler
    handlers = {
        "pipeline": cmd_pipeline,
        "extract": cmd_extract,
        "download": cmd_download,
        "enrich": cmd_enrich,
        "strategies": cmd_strategies,
        "xml": cmd_xml,
        "status": cmd_status,
    }
    
    handler = handlers.get(args.command)
    if handler:
        return handler(args, config)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
