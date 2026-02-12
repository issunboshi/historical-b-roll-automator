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
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Auto-load API keys from config file
import config  # noqa: F401

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
        "roles": {
            "extract": {"provider": "openai", "model": "gpt-4o-mini"},
            "extract-visuals": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
            "summarize": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
            "strategies": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
            "disambiguate": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
            "macro-visuals": {"provider": "openai", "model": "gpt-4o"},
        },
    },
}


# Roles that require Anthropic (they use client.beta.messages.parse with structured outputs)
PROVIDER_CONSTRAINTS = {
    "summarize": "anthropic",
    "strategies": "anthropic",
    "disambiguate": "anthropic",
}


def resolve_llm_for_role(config: Dict, role: str) -> Tuple[str, str]:
    """Resolve (provider, model) for a pipeline role.

    Precedence: role config > global config > hardcoded fallback.
    Warns and overrides if role has a provider constraint.
    """
    llm = config.get("llm", {})
    global_provider = llm.get("provider", "openai")
    global_model = llm.get("model", "gpt-4o-mini")

    role_cfg = llm.get("roles", {}).get(role, {})
    provider = role_cfg.get("provider") or global_provider
    model = role_cfg.get("model") or global_model

    constraint = PROVIDER_CONSTRAINTS.get(role)
    if constraint and provider != constraint:
        print(f"Warning: role '{role}' requires {constraint}, "
              f"ignoring '{provider}'", file=sys.stderr)
        provider = constraint
        if not role_cfg.get("model"):
            model = "claude-sonnet-4-5-20250929"

    return provider, model


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


# =============================================================================
# Pipeline Checkpointing
# =============================================================================

CHECKPOINT_VERSION = 1
CHECKPOINT_FILENAME = ".broll_checkpoint.json"

# Pipeline step names in execution order
PIPELINE_STEPS = ["extract", "extract-visuals", "enrich", "summarize", "merge-entities", "montages", "strategies", "disambiguate", "download", "markers", "xml"]


def compute_srt_hash(srt_path: Path) -> str:
    """Compute SHA256 hash of SRT file contents.

    Used to detect if the source file has changed between pipeline runs.

    Args:
        srt_path: Path to SRT file

    Returns:
        Hexadecimal SHA256 hash string
    """
    hasher = hashlib.sha256()
    with open(srt_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_checkpoint(output_dir: Path) -> Optional[Dict]:
    """Load checkpoint from output directory if it exists.

    Args:
        output_dir: Pipeline output directory

    Returns:
        Checkpoint dict or None if no valid checkpoint exists
    """
    checkpoint_path = output_dir / CHECKPOINT_FILENAME
    if not checkpoint_path.exists():
        return None

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)

        # Validate checkpoint version
        if checkpoint.get("version") != CHECKPOINT_VERSION:
            print(f"Warning: Checkpoint version mismatch (expected {CHECKPOINT_VERSION}, "
                  f"got {checkpoint.get('version')}). Starting fresh.", file=sys.stderr)
            return None

        return checkpoint
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load checkpoint: {e}. Starting fresh.", file=sys.stderr)
        return None


def save_checkpoint(output_dir: Path, checkpoint: Dict) -> None:
    """Save checkpoint to output directory.

    Uses atomic write pattern (write to temp, then rename) for safety.

    Args:
        output_dir: Pipeline output directory
        checkpoint: Checkpoint data to save
    """
    checkpoint_path = output_dir / CHECKPOINT_FILENAME
    temp_path = output_dir / f"{CHECKPOINT_FILENAME}.tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2)

        # Atomic rename
        temp_path.replace(checkpoint_path)
    except IOError as e:
        print(f"Warning: Failed to save checkpoint: {e}", file=sys.stderr)


def create_checkpoint(srt_path: Path, output_dir: Path) -> Dict:
    """Create a new checkpoint for a pipeline run.

    Args:
        srt_path: Path to source SRT file
        output_dir: Pipeline output directory

    Returns:
        New checkpoint dict with all steps marked as not completed
    """
    return {
        "version": CHECKPOINT_VERSION,
        "srt_path": str(srt_path.absolute()),
        "srt_hash": compute_srt_hash(srt_path),
        "output_dir": str(output_dir.absolute()),
        "created": datetime.now(timezone.utc).isoformat(),
        "steps": {
            step: {"completed": False, "timestamp": None}
            for step in PIPELINE_STEPS
        }
    }


def mark_step_completed(checkpoint: Dict, step_name: str) -> None:
    """Mark a pipeline step as completed in the checkpoint.

    Args:
        checkpoint: Checkpoint dict to update (modified in place)
        step_name: Name of the step to mark as completed
    """
    checkpoint["steps"][step_name] = {
        "completed": True,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def get_steps_to_run(checkpoint: Dict, from_step: Optional[str] = None) -> List[str]:
    """Determine which pipeline steps need to run.

    Args:
        checkpoint: Checkpoint dict
        from_step: Optional step name to start from (overrides checkpoint)

    Returns:
        List of step names that need to run, in order
    """
    if from_step:
        # Start from specified step, run all subsequent steps
        if from_step not in PIPELINE_STEPS:
            raise ValueError(f"Invalid step name: {from_step}. "
                           f"Valid steps: {', '.join(PIPELINE_STEPS)}")
        start_idx = PIPELINE_STEPS.index(from_step)
        return PIPELINE_STEPS[start_idx:]

    # Resume from checkpoint - find first incomplete step
    steps_to_run = []
    for step in PIPELINE_STEPS:
        step_info = checkpoint["steps"].get(step, {})
        if not step_info.get("completed", False):
            steps_to_run.append(step)

    return steps_to_run



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
    
    # Build command — resolve provider/model for the "extract" role
    role_provider, role_model = resolve_llm_for_role(config, "extract")
    provider = args.provider or role_provider
    model = args.model or role_model
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

    if hasattr(args, 'min_priority') and args.min_priority is not None:
        cmd.extend(["--min-priority", str(args.min_priority)])
    if getattr(args, 'verbose', False):
        cmd.append("-v")

    if getattr(args, 'interactive', False):
        cmd.append("--interactive")

    try:
        run_step("Downloading images from Wikipedia", cmd)
        print(f"\nEntities map updated: {map_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Image download failed: {e}", file=sys.stderr)
        return 1


def cmd_extract_visuals(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run visual element extraction from SRT (stats, quotes, processes, comparisons)."""
    script = resolve_script_path("srt_visual_elements.py")

    srt_path = Path(args.srt)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    elif args.output_dir:
        out_path = Path(args.output_dir) / "visual_elements.json"
    else:
        out_path = Path("visual_elements.json")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build command — resolve provider/model for the "extract-visuals" role
    # Honor legacy visuals_model config if roles.extract-visuals not set
    llm_config = config.get("llm", {})
    role_cfg = llm_config.get("roles", {}).get("extract-visuals", {})
    if not role_cfg.get("model") and llm_config.get("visuals_model"):
        # Legacy compat: visuals_model still honored when role not configured
        role_provider = llm_config.get("provider", "anthropic")
        role_model = llm_config["visuals_model"]
    else:
        role_provider, role_model = resolve_llm_for_role(config, "extract-visuals")
    provider = args.provider or role_provider
    model = args.model or role_model
    fps = args.fps or config.get("fps", 25.0)
    batch_size = getattr(args, 'batch_size', None) or config.get("visuals_batch_size", 5)

    cmd = [
        sys.executable, str(script),
        "--srt", str(srt_path),
        "--out", str(out_path),
        "--provider", provider,
        "--model", model,
        "--fps", str(fps),
        "--batch-size", str(batch_size),
    ]

    if args.context:
        cmd.extend(["--context", args.context])

    if args.delay:
        cmd.extend(["--delay", str(args.delay)])

    if getattr(args, 'no_batch', False):
        cmd.append("--no-batch")

    try:
        run_step("Extracting visual elements from transcript", cmd)
        print(f"\nVisual elements saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Visual element extraction failed: {e}", file=sys.stderr)
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


def cmd_summarize(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Generate transcript summary (topic, era, pervasive entities, clusters)."""
    script = resolve_script_path("summarize_transcript.py")

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities file not found: {map_path}", file=sys.stderr)
        return 1

    srt_path = Path(args.srt)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = map_path.parent / "transcript_summary.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve model for the "summarize" role
    _, role_model = resolve_llm_for_role(config, "summarize")
    model = getattr(args, 'model', None) or role_model

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--srt", str(srt_path),
        "--out", str(out_path),
        "--model", model,
    ]

    try:
        run_step("Generating transcript summary", cmd)
        print(f"\nTranscript summary saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Transcript summary failed: {e}", file=sys.stderr)
        return 1


def cmd_merge_entities(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Merge duplicate entities using summary clusters and fuzzy matching."""
    script = resolve_script_path("merge_entities.py")

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities file not found: {map_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = map_path.parent / "merged_entities.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--out", str(out_path),
    ]

    if hasattr(args, 'summary') and args.summary:
        cmd.extend(["--summary", str(args.summary)])

    try:
        run_step("Merging duplicate entities", cmd)
        print(f"\nMerged entities saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Entity merge failed: {e}", file=sys.stderr)
        return 1


def cmd_montages(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Detect montage/collage opportunities from entities."""
    script = resolve_script_path("detect_montages.py")

    entities_path = Path(args.entities)
    if not entities_path.exists():
        print(f"Error: entities file not found: {entities_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = entities_path.parent / "montages.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "--entities", str(entities_path),
        "--out", str(out_path),
    ]

    if hasattr(args, 'srt') and args.srt:
        cmd.extend(["--srt", str(args.srt)])

    if hasattr(args, 'window') and args.window:
        cmd.extend(["--window", str(args.window)])

    if hasattr(args, 'min_entities') and args.min_entities:
        cmd.extend(["--min-entities", str(args.min_entities)])

    try:
        run_step("Detecting montage opportunities", cmd)
        print(f"\nMontages saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Montage detection failed: {e}", file=sys.stderr)
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

    # Resolve model for the "strategies" role
    _, role_model = resolve_llm_for_role(config, "strategies")
    model = getattr(args, 'model', None) or role_model

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--out", str(out_path),
        "--model", model,
    ]

    if args.video_context:
        cmd.extend(["--video-context", args.video_context])

    if args.batch_size:
        cmd.extend(["--batch-size", str(args.batch_size)])

    if args.cache_dir:
        cmd.extend(["--cache-dir", args.cache_dir])

    era = getattr(args, 'era', None)
    if era:
        cmd.extend(["--era", era])

    summary = getattr(args, 'summary', None)
    if summary:
        cmd.extend(["--summary", summary])

    try:
        run_step("Generating search strategies", cmd)
        print(f"\nSearch strategies saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Search strategy generation failed: {e}", file=sys.stderr)
        return 1


def cmd_disambiguate(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Pre-compute Wikipedia disambiguation for all entities.

    This step runs BEFORE download to batch all disambiguation work,
    dramatically improving total pipeline time by enabling high parallelism.
    """
    script = resolve_script_path("disambiguate_entities.py")

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
        return 1

    parallel = getattr(args, 'disambig_parallel', None) or config.get("disambig_parallel", 10)
    min_priority = getattr(args, 'min_priority', None)
    if min_priority is None:
        min_priority = config.get("min_priority", 0.5)

    # Resolve model for the "disambiguate" role
    _, role_model = resolve_llm_for_role(config, "disambiguate")
    model = getattr(args, 'model', None) or role_model

    cmd = [
        sys.executable, str(script),
        "--map", str(map_path),
        "--parallel", str(parallel),
        "--min-priority", str(min_priority),
        "--model", model,
    ]

    if hasattr(args, 'cache_dir') and args.cache_dir:
        cmd.extend(["--cache-dir", args.cache_dir])

    if getattr(args, 'interactive', False):
        cmd.append("--interactive")

    try:
        run_step("Pre-computing Wikipedia disambiguation", cmd)
        print(f"\nDisambiguation complete: {map_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Disambiguation failed: {e}", file=sys.stderr)
        return 1


def cmd_xml(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Generate FCP XML from entities map."""
    script = resolve_script_path("generate_xml.py")
    
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

    cmd.extend(["--min-match-quality", args.min_match_quality])

    # Add montage clip duration if specified
    montage_duration = getattr(args, 'montage_clip_duration', None)
    if montage_duration:
        cmd.extend(["--montage-clip-duration", str(montage_duration)])

    # Frequency capping args
    max_placements = getattr(args, 'max_placements', None)
    if max_placements:
        cmd.extend(["--max-placements", str(max_placements)])
    pervasive_max = getattr(args, 'pervasive_max', None)
    if pervasive_max:
        cmd.extend(["--pervasive-max", str(pervasive_max)])
    summary_file = getattr(args, 'summary_file', None)
    if summary_file:
        cmd.extend(["--summary", str(summary_file)])

    try:
        run_step("Generating FCP XML timeline", cmd)
        print(f"\nXML saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"XML generation failed: {e}", file=sys.stderr)
        return 1


def cmd_pipeline(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run the full pipeline: extract -> enrich -> strategies -> disambiguate -> download -> xml.

    Supports checkpointing for resuming failed pipelines:
    - Use --resume to continue from last checkpoint
    - Use --from-step to start from a specific step
    """
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
    visual_elements_path = output_dir / "visual_elements.json"
    enriched_entities_path = output_dir / "enriched_entities.json"
    summary_path = output_dir / "transcript_summary.json"
    merged_entities_path = output_dir / "merged_entities.json"
    strategies_entities_path = output_dir / "strategies_entities.json"
    markers_path = output_dir / "visual_markers.edl"
    xml_path = output_dir / "broll_timeline.xml"

    # Handle checkpointing
    checkpoint = None
    from_step = getattr(args, 'from_step', None)
    resume = getattr(args, 'resume', False)

    if resume or from_step:
        checkpoint = load_checkpoint(output_dir)
        if checkpoint:
            # Validate SRT hash matches
            current_hash = compute_srt_hash(srt_path)
            if checkpoint.get("srt_hash") != current_hash:
                print("Warning: SRT file has changed since checkpoint. Starting fresh.",
                      file=sys.stderr)
                checkpoint = None

    if checkpoint is None:
        checkpoint = create_checkpoint(srt_path, output_dir)

    steps_to_run = get_steps_to_run(checkpoint, from_step)

    if not steps_to_run:
        print("\nAll steps already completed. Use --from-step to re-run specific steps.")
        return 0

    print(f"\n{'#'*60}")
    print(f"# B-Roll Pipeline")
    print(f"#")
    print(f"# Input:  {srt_path}")
    print(f"# Output: {output_dir}")
    print(f"# Steps:  {', '.join(steps_to_run)}")
    print(f"{'#'*60}")

    # Step 1: Extract entities
    if "extract" in steps_to_run:
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
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "extract")
        save_checkpoint(output_dir, checkpoint)

    # Step 2: Extract visual elements (optional, skip with --skip-visuals)
    skip_visuals = getattr(args, 'skip_visuals', False)
    if "extract-visuals" in steps_to_run and not skip_visuals:
        extract_visuals_args = argparse.Namespace(
            srt=str(srt_path),
            output=str(visual_elements_path),
            output_dir=None,
            provider=getattr(args, 'provider', None) or "anthropic",
            model=getattr(args, 'model', None),
            fps=args.fps,
            context=args.subject,  # Use --subject as context
            delay=args.extract_delay,
            batch_size=getattr(args, 'visuals_batch_size', 5),
            no_batch=False,
        )

        result = cmd_extract_visuals(extract_visuals_args, config)
        if result != 0:
            print("\nPipeline failed at: visual element extraction", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "extract-visuals")
        save_checkpoint(output_dir, checkpoint)
    elif "extract-visuals" in steps_to_run and skip_visuals:
        print("\n[Skipping visual element extraction (--skip-visuals)]")
        mark_step_completed(checkpoint, "extract-visuals")
        save_checkpoint(output_dir, checkpoint)

    # Step 3: Enrich entities
    if "enrich" in steps_to_run:
        enrich_args = argparse.Namespace(
            map=str(entities_path),
            srt=str(srt_path),
            output=str(enriched_entities_path),
        )

        result = cmd_enrich(enrich_args, config)
        if result != 0:
            print("\nPipeline failed at: entity enrichment", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "enrich")
        save_checkpoint(output_dir, checkpoint)

    # Step 4: Summarize transcript (topic, era, pervasive entities, clusters)
    skip_summary = getattr(args, 'skip_summary', False)
    if "summarize" in steps_to_run and not skip_summary:
        summarize_args = argparse.Namespace(
            map=str(enriched_entities_path),
            srt=str(srt_path),
            output=str(summary_path),
        )

        result = cmd_summarize(summarize_args, config)
        if result != 0:
            print("\nPipeline failed at: transcript summary", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "summarize")
        save_checkpoint(output_dir, checkpoint)
    elif "summarize" in steps_to_run and skip_summary:
        print("\n[Skipping transcript summary (--skip-summary)]")
        mark_step_completed(checkpoint, "summarize")
        save_checkpoint(output_dir, checkpoint)

    # Step 5: Merge duplicate entities
    if "merge-entities" in steps_to_run:
        merge_args = argparse.Namespace(
            map=str(enriched_entities_path),
            output=str(merged_entities_path),
            summary=str(summary_path) if summary_path.exists() else None,
        )

        result = cmd_merge_entities(merge_args, config)
        if result != 0:
            print("\nPipeline failed at: entity merge", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "merge-entities")
        save_checkpoint(output_dir, checkpoint)

    # Determine the best entities file for downstream steps
    # Prefer merged > enriched for strategies/disambiguate/download
    best_entities_path = merged_entities_path if merged_entities_path.exists() else enriched_entities_path

    # Step 6: Detect montage opportunities
    montages_path = output_dir / "montages.json"
    skip_montages = getattr(args, 'skip_montages', False)
    if "montages" in steps_to_run and not skip_montages:
        montages_args = argparse.Namespace(
            entities=str(entities_path),
            srt=str(srt_path),
            output=str(montages_path),
            window=getattr(args, 'montage_window', 8.0),
            min_entities=getattr(args, 'montage_min_entities', 3),
        )

        result = cmd_montages(montages_args, config)
        if result != 0:
            print("\nPipeline failed at: montage detection", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "montages")
        save_checkpoint(output_dir, checkpoint)
    elif "montages" in steps_to_run and skip_montages:
        print("\n[Skipping montage detection (--skip-montages)]")
        mark_step_completed(checkpoint, "montages")
        save_checkpoint(output_dir, checkpoint)

    # Step 7: Generate search strategies
    if "strategies" in steps_to_run:
        # Use era override if provided, otherwise strategies will auto-load summary
        era_override = getattr(args, 'era', None)

        strategies_args = argparse.Namespace(
            map=str(best_entities_path),
            output=str(strategies_entities_path),
            video_context=args.subject,  # Use --subject as video context
            batch_size=getattr(args, 'batch_size', None),
            cache_dir=getattr(args, 'cache_dir', None),
            era=era_override,
            summary=str(summary_path) if summary_path.exists() else None,
        )

        result = cmd_strategies(strategies_args, config)
        if result != 0:
            print("\nPipeline failed at: search strategy generation", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "strategies")
        save_checkpoint(output_dir, checkpoint)

    # Step 5: Pre-compute disambiguation (parallel, fast)
    if "disambiguate" in steps_to_run:
        disambiguate_args = argparse.Namespace(
            map=str(strategies_entities_path),
            disambig_parallel=getattr(args, 'disambig_parallel', 10),
            min_priority=getattr(args, 'min_priority', 0.5),
            cache_dir=getattr(args, 'cache_dir', None),
            interactive=getattr(args, 'interactive', False),
        )

        result = cmd_disambiguate(disambiguate_args, config)
        if result != 0:
            print("\nPipeline failed at: disambiguation", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "disambiguate")
        save_checkpoint(output_dir, checkpoint)

    # Step 6: Download images (now much faster with pre-computed disambiguation)
    if "download" in steps_to_run:
        download_args = argparse.Namespace(
            map=str(strategies_entities_path),
            images_per_entity=args.images_per_entity,
            delay=args.download_delay,
            parallel=args.parallel,
            no_svg_to_png=args.no_svg_to_png,
            min_priority=getattr(args, 'min_priority', None),
            verbose=getattr(args, 'verbose', False),
            output_dir=str(output_dir),  # Pass output directory to download step
            interactive=getattr(args, 'interactive', False),
        )

        result = cmd_download(download_args, config)
        if result != 0:
            print("\nPipeline failed at: image download", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "download")
        save_checkpoint(output_dir, checkpoint)

    # Step 7: Generate markers (if visual elements exist)
    if "markers" in steps_to_run:
        if visual_elements_path.exists():
            from tools.generate_markers import main as markers_main

            markers_args = [
                str(visual_elements_path),
                "--output", str(markers_path),
                "--format", "edl",
                "--fps", str(args.fps),
                "--timeline-name", f"{args.timeline_name} - Markers",
            ]

            result = markers_main(markers_args)
            if result != 0:
                print("\nPipeline failed at: Marker generation", file=sys.stderr)
                save_checkpoint(output_dir, checkpoint)
                return result
        else:
            print("Skipping markers: visual_elements.json not found")

        mark_step_completed(checkpoint, "markers")
        save_checkpoint(output_dir, checkpoint)

    # Step 11: Generate XML
    if "xml" in steps_to_run:
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
            min_match_quality=getattr(args, 'min_match_quality', 'high'),
            montage_clip_duration=getattr(args, 'montage_clip_duration', 0.6),
            max_placements=getattr(args, 'max_placements', 3),
            pervasive_max=getattr(args, 'pervasive_max', 2),
            summary_file=str(summary_path) if summary_path.exists() else None,
        )

        result = cmd_xml(xml_args, config)
        if result != 0:
            print("\nPipeline failed at: XML generation", file=sys.stderr)
            save_checkpoint(output_dir, checkpoint)
            return result

        mark_step_completed(checkpoint, "xml")
        save_checkpoint(output_dir, checkpoint)


    # Success summary
    print(f"\n{'#'*60}")
    print(f"# Pipeline Complete!")
    print(f"#")
    print(f"# Output files:")
    print(f"#   - Entities:       {entities_path}")
    if not skip_visuals and visual_elements_path.exists():
        print(f"#   - Visual Elements: {visual_elements_path}")
    print(f"#   - Enriched:       {enriched_entities_path}")
    if not skip_summary and summary_path.exists():
        print(f"#   - Summary:        {summary_path}")
    if merged_entities_path.exists():
        print(f"#   - Merged:         {merged_entities_path}")
    if not skip_montages and montages_path.exists():
        print(f"#   - Montages:       {montages_path}")
    print(f"#   - Strategies:     {strategies_entities_path}")
    if markers_path.exists():
        print(f"#   - Markers:        {markers_path}")
    print(f"#   - XML:            {xml_path}")
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

    # Show per-role LLM config
    print()
    print("LLM Roles:")
    role_names = ["extract", "extract-visuals", "summarize", "strategies", "disambiguate"]
    for role in role_names:
        provider, model = resolve_llm_for_role(config, role)
        constraint = PROVIDER_CONSTRAINTS.get(role)
        suffix = f" (requires {constraint})" if constraint else ""
        print(f"  {role:20s}  {provider}/{model}{suffix}")
    
    print()
    print("Scripts:")

    scripts = [
        ("srt_entities.py", "Entity extraction"),
        ("srt_visual_elements.py", "Visual element extraction"),
        ("enrich_entities.py", "Entity enrichment"),
        ("summarize_transcript.py", "Transcript summary"),
        ("merge_entities.py", "Entity merge"),
        ("detect_montages.py", "Montage detection"),
        ("generate_search_strategies.py", "Search strategy generation"),
        ("download_entities.py", "Image download"),
        ("generate_xml.py", "XML generation"),
        ("download_wikipedia_images.py", "Wikipedia downloader"),
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


def cmd_inject(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Inject manually-sourced images into an entity's image list."""
    from tools.download_entities import LICENSE_PRIORITY

    map_path = Path(args.map)
    if not map_path.exists():
        print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
        return 1

    with open(map_path, "r") as f:
        entities_map = json.load(f)

    # Find the entity (entities is a dict keyed by name)
    entity_name = args.entity
    entities = entities_map.get("entities", {})
    entity_data = entities.get(entity_name)

    if entity_data is None:
        print(f"Error: entity '{entity_name}' not found in {map_path}", file=sys.stderr)
        available = list(entities.keys())[:20]
        print(f"Available entities: {', '.join(available)}", file=sys.stderr)
        return 1

    # Validate image files
    image_paths: List[Path] = []
    for img_str in args.image:
        p = Path(img_str).resolve()
        if not p.exists():
            print(f"Error: image file not found: {p}", file=sys.stderr)
            return 1
        if not p.is_file():
            print(f"Error: not a file: {p}", file=sys.stderr)
            return 1
        image_paths.append(p)

    # Optionally copy images into the entity's download directory
    entity_dir = entity_data.get("download_dir")
    category = args.category or "public_domain"
    final_paths: List[Path] = []

    if entity_dir:
        dest_dir = Path(entity_dir) / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        for p in image_paths:
            dest = dest_dir / p.name
            if dest.resolve() != p.resolve():
                shutil.copy2(p, dest)
                print(f"  Copied {p.name} -> {dest}")
            final_paths.append(dest)
    else:
        final_paths = image_paths

    # Build image metadata entries (same 10 fields as harvest_images)
    injected = []
    for fp in final_paths:
        entry = {
            "path": str(fp),
            "filename": fp.name,
            "category": category,
            "license_short": args.license or "",
            "license_url": args.license_url or "",
            "source_url": args.source_url or "",
            "title": args.title or "",
            "author": args.author or "",
            "usage_terms": "",
            "suggested_attribution": "",
        }
        injected.append(entry)

    # Append to entity's images and re-sort by license priority
    images = entity_data.get("images", [])
    images.extend(injected)
    images.sort(key=lambda img: LICENSE_PRIORITY.get(img.get("category", ""), 99))
    entity_data["images"] = images

    # Write back
    with open(map_path, "w") as f:
        json.dump(entities_map, f, indent=2, ensure_ascii=False)

    print(f"\nInjected {len(injected)} image(s) into '{entity_name}':")
    for entry in injected:
        print(f"  {entry['filename']}  [{entry['category']}]  {entry['path']}")
    print(f"\nEntity now has {len(images)} total image(s).")
    print(f"Updated: {map_path}")
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
    p_pipeline.add_argument("--provider", choices=["openai", "anthropic", "ollama"], help="LLM provider")
    p_pipeline.add_argument("--model", help="LLM model name")
    p_pipeline.add_argument("--images-per-entity", type=int, help="Max images per entity")
    p_pipeline.add_argument("--duration", "-d", type=float, help="Clip duration in seconds")
    p_pipeline.add_argument("--gap", "-g", type=float, help="Min gap between clips in seconds")
    p_pipeline.add_argument("--tracks", "-t", type=int, help="Number of B-roll tracks")
    p_pipeline.add_argument("--allow-non-pd", action="store_true", help="Include non-public-domain images")
    p_pipeline.add_argument("--timeline-name", help="Name for the timeline")
    p_pipeline.add_argument("--extract-delay", type=float, default=0.2, help="Delay between LLM calls")
    p_pipeline.add_argument("--download-delay", type=float, default=0.1, help="Delay between download requests")
    p_pipeline.add_argument("-j", "--parallel", type=int, default=10,
                            help="Number of parallel downloads (default: 10)")
    p_pipeline.add_argument("--disambig-parallel", type=int, default=10,
                            help="Number of parallel disambiguation workers (default: 10)")
    p_pipeline.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion")
    p_pipeline.add_argument("--batch-size", type=int, help="Entities per LLM call (5-10)")
    p_pipeline.add_argument("--cache-dir", help="Wikipedia cache directory")
    p_pipeline.add_argument("--min-priority", type=float,
                            help="Minimum priority threshold for entity filtering (0.0 disables, default: 0.5)")
    p_pipeline.add_argument("-v", "--verbose", action="store_true",
                            help="Show per-entity skip messages during download")
    p_pipeline.add_argument("--min-match-quality", default='high',
                            choices=['high', 'medium', 'low', 'none'],
                            help="Minimum match quality to include in timeline (default: high)")
    p_pipeline.add_argument("--resume", action="store_true",
                            help="Resume from last checkpoint (skips completed steps)")
    p_pipeline.add_argument("--from-step",
                            choices=PIPELINE_STEPS,
                            help="Start from specific step (ignores checkpoint)")
    p_pipeline.add_argument("--skip-visuals", action="store_true",
                            help="Skip visual element extraction (stats, quotes, processes)")
    p_pipeline.add_argument("--visuals-batch-size", type=int, default=5,
                            help="Cues per LLM call for visual extraction (default: 5)")
    p_pipeline.add_argument("--montage-window", type=float, default=8.0,
                            help="Time window in seconds for montage density detection (default: 8.0)")
    p_pipeline.add_argument("--montage-min-entities", type=int, default=3,
                            help="Minimum entities for montage detection (default: 3)")
    p_pipeline.add_argument("--skip-montages", action="store_true",
                            help="Skip montage/collage opportunity detection")
    p_pipeline.add_argument("--montage-clip-duration", type=float, default=0.6,
                            help="Duration per image in montage sequences (default: 0.6s)")
    p_pipeline.add_argument("--era",
                            help="Override video era for search/disambiguation (e.g. '1857, mid-19th century India')")
    p_pipeline.add_argument("--pervasive-entities",
                            help="Comma-separated override list of pervasive entities")
    p_pipeline.add_argument("--max-placements", type=int, default=3,
                            help="Max clip placements per entity on timeline (default: 3)")
    p_pipeline.add_argument("--pervasive-max", type=int, default=2,
                            help="Max placements for pervasive/background entities (default: 2)")
    p_pipeline.add_argument("--skip-summary", action="store_true",
                            help="Skip the transcript summary step")
    p_pipeline.add_argument("-i", "--interactive", action="store_true",
                            help="Pause for interactive review during disambiguation and download")


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
    p_extract.add_argument("--provider", choices=["openai", "anthropic", "ollama"], help="LLM provider")
    p_extract.add_argument("--model", help="LLM model name")
    p_extract.add_argument("--delay", type=float, help="Delay between LLM calls")
    
    # Extract visuals command
    p_extract_visuals = subparsers.add_parser(
        "extract-visuals",
        help="Extract visual elements (stats, quotes, processes, comparisons) from SRT",
    )
    p_extract_visuals.add_argument("--srt", required=True, help="Path to SRT transcript")
    p_extract_visuals.add_argument("--output", "-o", help="Output JSON path")
    p_extract_visuals.add_argument("--output-dir", help="Output directory (creates visual_elements.json inside)")
    p_extract_visuals.add_argument("--fps", type=float, help="FPS for timecode conversion")
    p_extract_visuals.add_argument("--context", help="Video topic/context for better extraction")
    p_extract_visuals.add_argument("--provider", choices=["anthropic", "openai"], help="LLM provider (default: anthropic)")
    p_extract_visuals.add_argument("--model", help="LLM model name")
    p_extract_visuals.add_argument("--delay", type=float, help="Delay between LLM calls")
    p_extract_visuals.add_argument("--batch-size", type=int, default=5, help="Cues per LLM call (default: 5)")
    p_extract_visuals.add_argument("--no-batch", action="store_true", help="Process cues one at a time")

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
    p_download.add_argument("--min-priority", type=float,
                            help="Minimum priority threshold for entity filtering (0.0 disables, default: 0.5)")
    p_download.add_argument("-v", "--verbose", action="store_true",
                            help="Show per-entity skip messages")
    p_download.add_argument("-i", "--interactive", action="store_true",
                            help="Interactively retry failed downloads with alternative search terms")

    # Enrich command
    p_enrich = subparsers.add_parser(
        "enrich",
        help="Enrich entities with priority scores and transcript context",
    )
    p_enrich.add_argument("--map", required=True, help="Path to entities_map.json")
    p_enrich.add_argument("--srt", required=True, help="Path to original SRT file")
    p_enrich.add_argument("--output", "-o", help="Output JSON path (default: enriched_entities.json)")

    # Summarize command
    p_summarize = subparsers.add_parser(
        "summarize",
        help="Generate transcript summary (topic, era, pervasive entities, clusters)",
    )
    p_summarize.add_argument("--map", required=True, help="Path to enriched_entities.json")
    p_summarize.add_argument("--srt", required=True, help="Path to original SRT file")
    p_summarize.add_argument("--output", "-o", help="Output JSON path")

    # Merge entities command
    p_merge = subparsers.add_parser(
        "merge-entities",
        help="Merge duplicate entities using summary clusters and fuzzy matching",
    )
    p_merge.add_argument("--map", required=True, help="Path to enriched_entities.json")
    p_merge.add_argument("--summary", help="Path to transcript_summary.json")
    p_merge.add_argument("--output", "-o", help="Output JSON path")

    # Montages command
    p_montages = subparsers.add_parser(
        "montages",
        help="Detect montage/collage opportunities from entities",
    )
    p_montages.add_argument("--entities", required=True, help="Path to entities_map.json")
    p_montages.add_argument("--srt", help="Path to original SRT (for enumeration detection)")
    p_montages.add_argument("--output", "-o", help="Output JSON path")
    p_montages.add_argument("--window", type=float, default=8.0,
                            help="Time window in seconds for density detection (default: 8.0)")
    p_montages.add_argument("--min-entities", type=int, default=3,
                            help="Minimum entities for density montage (default: 3)")

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
    p_strategies.add_argument("--era", help="Era/time period for search disambiguation")
    p_strategies.add_argument("--summary", help="Path to transcript_summary.json")

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
    p_xml.add_argument("--min-match-quality", default='high',
                       choices=['high', 'medium', 'low', 'none'],
                       help="Minimum match quality to include in timeline (default: high)")
    p_xml.add_argument("--montage-clip-duration", type=float, default=0.6,
                       help="Duration per image in montage sequences (default: 0.6s)")
    p_xml.add_argument("--max-placements", type=int, default=3,
                       help="Max clip placements per entity on timeline (default: 3)")
    p_xml.add_argument("--pervasive-max", type=int, default=2,
                       help="Max placements for pervasive entities (default: 2)")
    p_xml.add_argument("--summary-file",
                       help="Path to transcript_summary.json (for pervasive entity list)")

    # Disambiguate command
    p_disambig = subparsers.add_parser(
        "disambiguate",
        help="Pre-compute Wikipedia disambiguation for all entities",
    )
    p_disambig.add_argument("--map", required=True, help="Path to entities_map.json")
    p_disambig.add_argument("-j", "--disambig-parallel", type=int, default=10,
                            help="Number of parallel disambiguation workers (default: 10)")
    p_disambig.add_argument("--min-priority", type=float, default=0.5,
                            help="Minimum priority threshold (0.0 disables)")
    p_disambig.add_argument("--cache-dir", help="Wikipedia cache directory")
    p_disambig.add_argument("-i", "--interactive", action="store_true",
                            help="Interactively review uncertain disambiguations")

    # Status command
    subparsers.add_parser(
        "status",
        help="Show configuration and check script availability",
    )

    # Inject command — manually add images to an entity
    p_inject = subparsers.add_parser(
        "inject",
        help="Inject manually-sourced images into an entity's image list",
    )
    p_inject.add_argument("--map", required=True, help="Path to entities_map.json")
    p_inject.add_argument("--entity", required=True, help="Entity name (must exist in map)")
    p_inject.add_argument("--image", required=True, action="append",
                          help="Path to image file (can be repeated)")
    p_inject.add_argument("--category", default="public_domain",
                          help="License category (default: public_domain)")
    p_inject.add_argument("--license", default="",
                          help="License short name (e.g. 'CC BY 4.0')")
    p_inject.add_argument("--license-url", default="",
                          help="License URL")
    p_inject.add_argument("--source-url", default="",
                          help="Where the image was sourced from")
    p_inject.add_argument("--author", default="",
                          help="Image author/creator")
    p_inject.add_argument("--title", default="",
                          help="Image title")

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
        "extract-visuals": cmd_extract_visuals,
        "download": cmd_download,
        "enrich": cmd_enrich,
        "summarize": cmd_summarize,
        "merge-entities": cmd_merge_entities,
        "montages": cmd_montages,
        "strategies": cmd_strategies,
        "disambiguate": cmd_disambiguate,
        "xml": cmd_xml,
        "status": cmd_status,
        "inject": cmd_inject,
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
