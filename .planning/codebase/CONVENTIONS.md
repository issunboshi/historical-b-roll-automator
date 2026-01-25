# Coding Conventions

**Analysis Date:** 2026-01-25

## Naming Patterns

**Files:**
- Snake case for all Python files: `broll.py`, `srt_entities.py`, `generate_broll_xml.py`, `download_entities.py`, `wikipedia_image_downloader.py`
- Main executable file at root: `broll.py`
- Tool scripts organized in `tools/` subdirectory: `tools/srt_entities.py`, `tools/download_entities.py`
- Descriptive names indicating function: `place_broll.lua`, `entities_map.json` (data files)

**Functions:**
- Snake case for all function names: `find_config_file()`, `load_config()`, `resolve_script_path()`, `run_step()`, `cmd_extract()`, `safe_print()`, `srt_timecode_to_seconds()`, `seconds_to_frames()`, `frames_to_timecode()`
- Prefixed function names for categories:
  - `cmd_*` for CLI command handlers: `cmd_pipeline()`, `cmd_extract()`, `cmd_download()`, `cmd_xml()`, `cmd_status()`
  - `call_*` for function calls to external services: `call_llm_extract()`
  - `safe_*` for thread-safe utilities: `safe_print()`, `safe_folder_name()`
  - `path_*` for path manipulation: `path_to_file_url()`
  - `parse_*`, `read_*`, `get_*`, `search_*`, `build_*` for specific operations

**Variables:**
- Snake case for all variables: `output_dir`, `fps`, `timeline_name`, `clip_duration_sec`, `max_frame`, `file_registry`, `track_placements`
- All lowercase for module-level constants: `DEFAULT_CONFIG`, `WIKIPEDIA_API`, `DEFAULT_USER_AGENT`, `REQUEST_DELAY_S`, `MAX_RETRIES`, `RETRY_BACKOFF_S`, `SVG_TO_PNG`, `SVG_PNG_WIDTH`, `BLACKLIST_BASENAME_PATTERNS`, `RELATIVE_TIME_PREFIX_RE`, `WHITESPACE_RE`, `EVENT_KEYWORDS_RE`
- Collection names use plural: `clips`, `placements`, `cues`, `entities`, `occurrences`, `images`, `tracks_dict`, `file_registry`

**Types:**
- Type hints use standard Python types from `typing`: `Optional`, `Dict`, `List`, `Tuple`, `Any`, `Iterable`
- Type hints on function signatures: e.g., `def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:`
- Dataclass for structured data: `@dataclass class SrtCue:` with typed fields

## Code Style

**Formatting:**
- 4-space indentation (standard Python)
- Max line length ~100-120 characters observed (most lines under 100)
- Blank lines between logical sections in functions
- Two blank lines between top-level functions
- No trailing whitespace

**Linting:**
- No linter configuration files detected (`.pylintrc`, `.flake8`, etc.)
- Code follows PEP 8 naming conventions throughout
- String formatting uses f-strings: `f"Output: {output_dir}"`
- Dictionary operations prefer `.get()` for safe access: `config.get("llm", {}).get("provider", "openai")`

## Import Organization

**Order (observed pattern in `broll.py`):**
1. Future annotations: `from __future__ import annotations`
2. Standard library (alphabetically): `argparse`, `json`, `os`, `subprocess`, `sys`
3. Standard library modules with longer names: `from pathlib import Path`, `from typing import Any, Dict, List, Optional`
4. Try-except for optional imports: `try: import yaml` with fallback flag `YAML_AVAILABLE = True`

**Order (observed in `generate_broll_xml.py`):**
1. Future annotations: `from __future__ import annotations`
2. Standard library: `argparse`, `json`, `os`, `re`, `sys`, `uuid`
3. Standard library extended imports: `from datetime import datetime`, `from pathlib import Path`, `from urllib.parse import quote`, `from xml.etree import ElementTree as ET`, `from xml.dom import minidom`

**Path Aliases:**
- No path aliases detected; all imports are standard library or installed packages
- Paths resolved explicitly: `Path(__file__).parent`, `Path.cwd()`, `Path.home()`

## Error Handling

**Patterns:**
- Try-except blocks for file I/O operations: `with open(path, "r", encoding="utf-8") as f:`
- Exception handling with fallback: Try optional YAML import, fall back to defaults if not available
- Error messages to stderr: `print(..., file=sys.stderr)`
- System exit on critical errors: `sys.exit(1)` with error message
- CalledProcessError catching for subprocess: `except subprocess.CalledProcessError as e: print(..., file=sys.stderr)`
- Generic exception handling with logging: `except Exception as e: print(f"Warning: ...")`
- KeyboardInterrupt handling at main entry point: `except KeyboardInterrupt: ... sys.exit(130)`

**Return codes:**
- 0 for success
- 1 for generic errors
- 130 for interruption (SIGINT)

## Logging

**Framework:** No logger framework (logging module) detected

**Patterns:**
- Console output via `print()` for user-facing messages
- Progress output to stdout: `print(f"Placing {len(placements)} clips, skipped {skipped}")`
- Warnings/errors to stderr: `print(..., file=sys.stderr)`
- Separators for readability: `print(f"\n{'='*60}")`, `print(f"\n{'#'*60}")`
- Thread-safe print wrapper where parallelism exists: `def safe_print(*args, **kwargs): with _print_lock: print(...)`

## Comments

**When to Comment:**
- Detailed docstrings for all public functions explaining purpose, arguments, return types
- Inline comments explaining regex patterns and complex logic
- Comments for rate limiting, retry logic, and special handling
- Comments on workarounds: e.g., "These need to be re-encoded so %2C becomes %252C in the URL"

**Format (observed):**
- Module-level docstring at top describing purpose and usage
- Function docstrings explaining arguments and return values
- Examples in docstrings for CLI usage

**Example from `broll.py`:**
```python
"""
broll.py - Unified CLI for the B-Roll Finder pipeline.

This script orchestrates the full B-roll generation workflow:
  1. Extract entities from an SRT transcript (via LLM)
  2. Download images from Wikipedia for each entity
  3. Generate FCP XML for import into DaVinci Resolve

Usage:
  # Full pipeline (most common)
  python broll.py pipeline --srt video.srt --output-dir ./output --fps 24
"""
```

## Function Design

**Size:**
- Functions generally 10-50 lines
- Long functions (50-100 lines) are command handlers that orchestrate steps
- `create_fcp_xml()` is 180 lines but is a complex XML generation function with clear sections

**Parameters:**
- 2-6 parameters typical for most functions
- Use `argparse.Namespace` for CLI argument passing between functions
- Dict for configuration passing: `config: Dict[str, Any]`
- Sensible defaults in function signatures: `def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:`

**Return Values:**
- Functions return data objects or status codes (0/1) consistently
- None for operations with side effects (file writes, prints)
- Dicts, Lists, or strings for data-returning functions
- Exit codes (0 for success, 1 for failure) for command handlers

## Module Design

**Exports:**
- No `__all__` declarations observed
- Public functions start with regular names; private helpers use leading underscore: `_format_hhmmss_frames_to_srt()`, `_strip_speaker_lines()`
- Main functionality in module-level function definitions

**Barrel Files:**
- No barrel files detected
- Single-purpose modules at root and in `tools/` directory
- Imports resolved at call site, not aggregated

## Command-Line Interface

**Pattern:**
- Main script `broll.py` uses `argparse.ArgumentParser` with subparsers for commands
- Each command has dedicated parser: `p_pipeline`, `p_extract`, `p_download`, `p_xml`, `p_status`
- Arguments use lowercase with hyphens: `--output-dir`, `--fps`, `--timeline-name`
- Short forms for common options: `-o`, `-d`, `-g`, `-t`, `-j`
- Type conversion in argparse: `type=float`, `type=int`, `action="store_true"`
- Help text on all arguments
- Required vs optional arguments explicit
- Default values in argparse definitions or in help text

**Example from `broll.py`:**
```python
p_pipeline.add_argument("--srt", required=True, help="Path to SRT transcript")
p_pipeline.add_argument("--fps", type=float, help="Timeline frame rate")
p_pipeline.add_argument("--output-dir", "-o", help="Output directory (default: SRT filename)")
```

## Data Structures

**JSON data:**
- `entities_map.json`: Entity data with occurrences, timecodes, and images
- Structure: `{"entities": {entity_name: {images: [...], occurrences: [...]}}}`
- Loaded with `json.load()` and `json.dump()`

**Configuration:**
- YAML config file: `broll_config.yaml` (optional)
- Python dict merging for config: default values merged with file values
- CLI arguments override all

**File paths:**
- Always resolved to absolute paths: `Path.abspath()`, `.resolve()`
- Path objects preferred: `Path()` from pathlib
- Parent directory creation: `path.parent.mkdir(parents=True, exist_ok=True)`

---

*Convention analysis: 2026-01-25*
