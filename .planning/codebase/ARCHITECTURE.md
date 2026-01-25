# Architecture

**Analysis Date:** 2026-01-25

## Pattern Overview

**Overall:** Three-stage sequential pipeline with subprocess-based orchestration and immutable JSON state passing.

**Key Characteristics:**
- **Stage-based processing**: Entity extraction → image download → timeline generation, each stage reads/writes `entities_map.json`
- **Subprocess isolation**: `broll.py` spawns child processes for each stage to allow independent scaling and error isolation
- **Configuration cascading**: CLI flags > environment variables > YAML config file > hardcoded defaults
- **File-based data interchange**: Central `entities_map.json` accumulates metadata as it flows through pipeline

## Layers

**CLI/Orchestration Layer:**
- Purpose: Parse arguments, manage configuration, dispatch to tool scripts via subprocess
- Location: `broll.py` (main entry point)
- Contains: Argument parsing, config loading (`load_config()`, `find_config_file()`), subprocess spawning (`run_step()`), pipeline coordination (`cmd_pipeline()`)
- Depends on: Tool scripts (via `subprocess.run()`), YAML config, Python `argparse`
- Used by: End users via command line; does NOT directly execute stage logic

**Entity Extraction Layer:**
- Purpose: Parse SRT transcript and use LLM (OpenAI/Ollama) to extract named entities per cue
- Location: `tools/srt_entities.py`
- Contains: SRT parsing (`parse_srt()`), LLM API calls (`call_llm_extract()`), entity deduplication, canonical name resolution
- Depends on: `requests` library, LLM API (OpenAI or Ollama), environment variables (OPENAI_API_KEY, OPENAI_API_BASE, OLLAMA_HOST)
- Used by: Spawned by `cmd_extract()` in broll.py; reads SRT, outputs `entities_map.json`

**Image Download Layer:**
- Purpose: Map extracted entities to Wikipedia pages and download representative images with license metadata
- Location: `tools/download_entities.py` (orchestrator), `wikipedia_image_downloader.py` (core downloader)
- Contains: Entity-to-image mapping, parallel download execution (ThreadPoolExecutor), license classification, image metadata collection
- Depends on: `wikipedia_image_downloader.py`, `requests`, `BeautifulSoup4`, parallel execution (threading)
- Used by: Spawned by `cmd_download()` in broll.py; reads and modifies `entities_map.json` with image paths and license info

**Timeline Generation Layer:**
- Purpose: Convert enriched `entities_map.json` to FCP 7 XML timeline for DaVinci Resolve import
- Location: `generate_broll_xml.py`
- Contains: Clip placement logic, timecode conversion (`seconds_to_frames()`, `frames_to_timecode()`), XML structure building (`build_xml_timeline()`), track assignment
- Depends on: `xml.etree.ElementTree`, JSON input, path manipulation
- Used by: Spawned by `cmd_xml()` in broll.py; reads `entities_map.json`, outputs `broll_timeline.xml`

**Resolve Integration Layer:**
- Purpose: Direct manipulation of DaVinci Resolve project via scripting (alternative to XML import)
- Location: `resolve_integration/place_broll.lua` (primary), `resolve_integration/place_broll.py` (optional Python wrapper)
- Contains: JSON decoder (embedded in Lua), Resolve API bindings, media pool bin creation, clip placement on timeline
- Depends on: Resolve Python API (`DaVinciResolveScript` module), Lua 5.1 environment
- Used by: User invokes from within Resolve scripting console; reads `entities_map.json`, directly modifies active project

## Data Flow

**Full Pipeline:**

```
Input: SRT transcript (timecodes + dialogue)
           ↓
[Stage 1: Extract Entities]
  - tools/srt_entities.py spawned by broll.py
  - Parse SRT with 3 timecode format support
  - Call LLM (OpenAI/Ollama) per cue
  - Extract: people, places, concepts, events
  - Deduplicate across 5-second windows
  - Output: entities_map.json
           ↓
entities_map.json:
{
  "Barack Obama": {
    "type": "person",
    "canonical": "Barack Obama",
    "occurrences": [
      {
        "cue_index": 5,
        "start": "00:00:15,200",
        "end": "00:00:22,500",
        "text": "Barack Obama became president..."
      }
    ],
    "images": []  ← populated by next stage
  },
  ...
}
           ↓
[Stage 2: Download Images]
  - tools/download_entities.py spawned by broll.py
  - For each entity in map:
    - Call wikipedia_image_downloader.py in subprocess
    - Download N images (default 3)
    - Classify by license: public_domain, cc_by, cc_by_sa, other_cc, restricted_nonfree, unknown
  - Parallel execution: 4 workers by default
  - Update entities_map.json with image paths and metadata
           ↓
entities_map.json (enriched):
{
  "Barack Obama": {
    ...,
    "images": [
      {
        "path": "/Users/.../Barack Obama/public_domain/image1.jpg",
        "license": "public_domain",
        "category": "public_domain",
        "license_short": "CC0",
        "license_url": "...",
        "source_url": "https://commons.wikimedia.org/wiki/..."
      },
      { ... },
      { ... }
    ]
  },
  ...
}
           ↓
[Stage 3: Generate Timeline XML]
  - generate_broll_xml.py spawned by broll.py
  - Read entities_map.json
  - Calculate placements:
    - For each occurrence of each entity
    - Get first available image
    - Assign to track (round-robin: V2, V3, V4, V5)
    - Calculate frame position from timecode
    - Ensure min_gap_seconds between clips
  - Build FCP 7 XML structure
    - Master clips in B-Roll bin
    - Video sequence with interleaved clips on tracks
    - File references with proper file:// URLs
  - Output: broll_timeline.xml
           ↓
Output: broll_timeline.xml (ready for Resolve import)
       + Downloaded images directory structure
       + Optional ATTRIBUTION_USED.tsv (for non-PD images)
```

**State Management:**

- **Persistent checkpoint**: `entities_map.json` is the canonical state; allows resume from any stage
- **Ephemeral**: SRT file, config files (read-only inputs)
- **Transient outputs**: XML file, downloaded images, attribution files (can be regenerated)

## Key Abstractions

**SrtCue:**
- Purpose: Single subtitle entry with timing and dialogue
- Examples: Defined in `tools/srt_entities.py` as dataclass: `SrtCue(index, start, end, text)`
- Pattern: Data transfer object; parser produces list of these from SRT file
- Parsing handles: Standard SRT (index on line 1), VTT format (dots instead of commas), frame-based timecodes

**Entity:**
- Purpose: Named entity with metadata (type, occurrences, images, canonical form)
- Examples: Keys in `entities_map.json` dict; structure shown in data flow above
- Pattern: Mutable JSON dict that accumulates metadata through pipeline stages
- Fields: `type` (person/place/concept/event), `canonical` (Wikipedia-style name), `occurrences` (list), `images` (list)

**Occurrence:**
- Purpose: Specific mention of entity in transcript (timecode + context)
- Examples: `occurrences` array in each entity
- Pattern: Dict with keys: `cue_index`, `start`, `end`, `text` (the cue text containing entity)
- Used for: Calculating placement timecodes in XML generation

**Image Record:**
- Purpose: Downloaded image with license and source metadata
- Examples: `images` array in each entity
- Pattern: Dict with keys: `path` (filesystem), `license` (short code), `category` (folder name), `license_url`, `source_url`
- Used for: XML generation selects first available image per occurrence; filtering by license (PD vs. non-PD)

**Placement:**
- Purpose: Computed clip instance positioned on video track
- Examples: Intermediate structure in `generate_broll_xml.py` (not persisted)
- Pattern: Dict with keys: `entity_name`, `path`, `track`, `frame`, `duration_frames`
- Calculation: For each occurrence → next available track (round-robin) → frame from timecode → duration from config

**License Category:**
- Purpose: Organize downloaded images by reuse rights
- Examples: Folder names in entity directories: `public_domain`, `cc_by`, `cc_by_sa`, `other_cc`, `restricted_nonfree`, `unknown`
- Pattern: Determined during download; affects `--allow-non-pd` filtering in XML generation and attribution requirements

## Entry Points

**Command: `python broll.py pipeline --srt <file> [options]`**
- Location: `broll.py` function `cmd_pipeline()`
- Triggers: User execution with required SRT file
- Responsibilities: Orchestrate extract → download → xml stages sequentially; stop pipeline on first failure; report summary on success

**Command: `python broll.py extract --srt <file> --out <path> [options]`**
- Location: `broll.py` function `cmd_extract()`
- Triggers: User execution; also called by pipeline
- Responsibilities: Spawn `tools/srt_entities.py` subprocess; validate SRT exists; output entities_map.json

**Command: `python broll.py download --map <file> [options]`**
- Location: `broll.py` function `cmd_download()`
- Triggers: User execution; also called by pipeline
- Responsibilities: Spawn `tools/download_entities.py` subprocess; read/write entities_map.json; manage parallel downloads

**Command: `python broll.py xml --map <file> [options]`**
- Location: `broll.py` function `cmd_xml()`
- Triggers: User execution; also called by pipeline
- Responsibilities: Spawn `generate_broll_xml.py` subprocess; validate entities_map exists; generate FCP 7 XML

**Script: `python tools/srt_entities.py --srt <path> --out <path> [options]`**
- Location: `tools/srt_entities.py` function `main()`
- Triggers: Spawned by `cmd_extract()`; can be run standalone
- Responsibilities: Parse SRT file → call LLM per cue → deduplicate entities → write entities_map.json
- Exit codes: 0 (success), 1 (error), 2 (no cues parsed)

**Script: `python tools/download_entities.py --map <file> [options]`**
- Location: `tools/download_entities.py` function `main()`
- Triggers: Spawned by `cmd_download()`; can be run standalone
- Responsibilities: Read entities_map.json → spawn parallel Wikipedia downloads → update map with image paths/metadata
- Parallel: 4 workers by default (configurable with `--parallel` flag)

**Script: `python generate_broll_xml.py <entities_map> [options]`**
- Location: `generate_broll_xml.py` function `main()`
- Triggers: Spawned by `cmd_xml()`; can be run standalone
- Responsibilities: Read entities_map.json → compute placements → build FCP 7 XML → write file
- Exit codes: 0 (success), 1 (file not found or invalid)

**Resolve Integration: Inside Resolve scripting console**
- Location: `resolve_integration/place_broll.lua` or wrapped by `place_broll.py`
- Triggers: User selects from Resolve Scripts menu or calls from Python API
- Responsibilities: Load entities_map.json → create media pool bins → place clips on timeline using Resolve API
- Alternative: Bypasses XML import; directly manipulates active Resolve project

## Error Handling

**Strategy:** Fail-fast at each stage with clear error reporting to stderr; pipeline stops on first subprocess failure.

**Patterns:**

- **File validation**: Before subprocess spawn, check file exists; print error and return exit code 1
  - Example: `broll.py` lines 180-182, 214-216 check SRT and entities_map exist

- **Subprocess failure**: Catch `subprocess.CalledProcessError`, report stage name, stop pipeline
  - Example: `cmd_pipeline()` checks return code after each step (line 303, 317, 334)

- **JSON parsing errors**: Try-except in stage scripts; re-raise on invalid JSON from LLM or file read
  - Example: `tools/srt_entities.py` wraps LLM response in json.loads() with try-except

- **LLM API errors**: API calls include timeout (60s); HTTP errors printed with response text; treated as hard failure
  - Example: `tools/srt_entities.py` `resp.raise_for_status()` on line 177

- **Image download failures**: Individual entity download failures logged but don't block others (ThreadPoolExecutor in download_entities.py)
  - Example: `download_entity()` catches `subprocess.CalledProcessError`, returns failure tuple; main loop continues

- **Missing images in XML**: XML generated even if some images missing; Resolve handles missing media on import (user re-links)
  - Example: `generate_broll_xml.py` does not validate image paths exist

- **Configuration errors**: Missing optional config files treated as non-error; defaults applied
  - Example: `load_config()` prints warning to stderr if YAML parse fails

## Cross-Cutting Concerns

**Logging:**
- No structured logging; uses print to stdout/stderr
- **CLI orchestrator** (`broll.py`): Step headers with "="*60 separator, progress on each command
- **Stage scripts**: Progress updates with indices "[idx/total]" for long operations
- Subprocess output: Captured or passed through depending on `capture_output` flag

**Validation:**

- **SRT parsing**: Three timecode format support: standard HH:MM:SS,mmm → HH:MM:SS:FF frames → VTT with dots
  - Implemented in `parse_srt()` with cascading regex patterns (lines 69-130 in srt_entities.py)

- **Entity structure**: LLM response must be valid JSON with required keys
  - Enforced in `call_llm_extract()` with json.loads() and key checks (lines 196-207 in srt_entities.py)

- **Image paths**: Windows and macOS paths converted to file:// URLs with proper escaping
  - Implemented in `path_to_file_url()` in generate_broll_xml.py (lines 41-57)

- **Timecodes**: Validated during SRT parsing; frame counts computed from FPS
  - Implemented in `seconds_to_frames()` and `frames_to_timecode()` (lines 69-84 in generate_broll_xml.py)

**Authentication:**

- **OpenAI**: OPENAI_API_KEY required from environment; optional OPENAI_API_BASE (defaults to https://api.openai.com/v1)
  - Checked in `srt_entities.py` lines 165-177 before API call

- **Ollama**: OLLAMA_HOST optional from environment (defaults to http://127.0.0.1:11434)
  - Checked in `srt_entities.py` lines 179-191 before API call

- **Wikipedia**: Public API; no authentication required; User-Agent header expected as courtesy
  - Configured in `wikipedia_image_downloader.py` with custom user-agent

**Configuration:**

- **Resolution order** (highest to lowest priority):
  1. CLI flags: `--fps`, `--duration`, `--images-per-entity`, etc.
  2. Environment variables: `OPENAI_API_KEY`, `OLLAMA_HOST`, `WIKI_IMG_OUTPUT_DIR`
  3. Config file: `broll_config.yaml` (searched in cwd then script directory)
  4. Hardcoded defaults: `DEFAULT_CONFIG` dict in broll.py (lines 41-52)

- **Config file format**: YAML with keys matching DEFAULT_CONFIG structure
  - Merge logic: `load_config()` recursively updates dict with file values (lines 67-88)

**Rate Limiting and Politeness:**

- **LLM calls**: `--delay` flag (default 0.2s) in srt_entities.py between requests
- **Wikipedia API**: `--delay` flag (default 0.3s) in wikipedia_image_downloader.py between requests
- **HTTP retry**: Exponential backoff on 429/5xx errors (max 5 retries by default)
- **Parallel downloads**: Configurable worker count (default 4) to limit concurrent load

**Media Path Handling:**

- **Image discovery**: `wikipedia_image_downloader.py` filters by MIME type (image/* only), avoids audio/video
- **SVG conversion**: Automatic SVG → PNG conversion with 3000px width (can be disabled with `--no-svg-to-png`)
- **Folder naming**: Entity names sanitized for filesystem safety (`safe_folder_name()` in download_entities.py)
- **File URL encoding**: Special characters double-encoded in file:// URLs for Resolve compatibility

---

*Architecture analysis: 2026-01-25*
