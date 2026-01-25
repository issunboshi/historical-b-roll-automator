# Architecture

**Analysis Date:** 2026-01-25

## Pattern Overview

**Overall:** Pipeline-based multi-stage data transformation with external service integrations (LLM, Wikipedia API, DaVinci Resolve).

**Key Characteristics:**
- Sequential processing pipeline: SRT transcript → entity extraction → image download → XML timeline generation
- Modular script design with independent CLI entry points
- Unified orchestration via `broll.py` CLI dispatcher
- Subprocess-based interprocess communication between stages
- File-based data interchange using JSON maps as canonical state
- External dependency on LLM providers (OpenAI/Ollama) and Wikipedia API

## Layers

**CLI/Orchestration Layer:**
- Purpose: Command dispatch, configuration management, pipeline workflow coordination
- Location: `broll.py`
- Contains: Argument parsing, config loading, subprocess spawning, step coordination
- Depends on: Tool scripts (via subprocess), config files (YAML)
- Used by: End users via command line

**Entity Extraction Layer:**
- Purpose: Parse SRT transcripts and use LLM to identify people, places, concepts, events in each cue
- Location: `tools/srt_entities.py`
- Contains: SRT parsing, LLM API communication (OpenAI/Ollama), entity deduplication, temporal filtering
- Depends on: HTTP requests library, OPENAI_API_KEY or OLLAMA_HOST environment variables
- Used by: `broll.py pipeline`, `broll.py extract` commands

**Image Download Layer:**
- Purpose: Resolve extracted entities to Wikipedia pages and download images with license metadata
- Location: `tools/download_entities.py`, `wikipedia_image_downloader.py`
- Contains: Entity-to-Wikipedia mapping, parallel download execution, license classification, SVG-to-PNG conversion
- Depends on: `wikipedia_image_downloader.py`, file I/O, image processing (Pillow, Cairo for SVG)
- Used by: `broll.py pipeline`, `broll.py download` commands

**Timeline Generation Layer:**
- Purpose: Convert entities map to FCP 7 XML timeline for DaVinci Resolve import
- Location: `generate_broll_xml.py`
- Contains: Placement logic, XML generation, frame/timecode calculations, file reference resolution
- Depends on: XML ElementTree library, entities_map.json input
- Used by: `broll.py pipeline`, `broll.py xml` commands

**Resolve Integration Layer:**
- Purpose: Direct Lua-based manipulation of DaVinci Resolve project (alternative to XML import)
- Location: `resolve_integration/place_broll.py` (Python wrapper), `resolve_integration/place_broll.lua` (Lua script)
- Contains: JSON parsing, Resolve scripting API interaction, media pool management
- Depends on: Resolve scripting environment (must run inside Resolve)
- Used by: Manual invocation inside Resolve scripting console

## Data Flow

**Full Pipeline Flow:**

1. **Input:** SRT transcript file (HH:MM:SS,mmm timecode + dialogue per cue)
2. **Stage 1 - Extract:** `srt_entities.py` parses SRT, calls LLM per cue, produces `entities_map.json`
   - Each cue text → LLM → {people, places, concepts, events, primary_entity}
   - Entities deduplicated across 5-second time windows
   - JSON structure: `{entity_name: {occurrences: [...], images: [...], license: ...}, ...}`
3. **Stage 2 - Download:** `download_entities.py` reads map, calls Wikipedia downloader per entity
   - Each entity → Wikipedia search → top images → download to disk
   - License classification (PD, CC-BY, CC-BY-SA, other CC, restricted, unknown)
   - Metadata appended to entities_map.json
4. **Stage 3 - XML Generation:** `generate_broll_xml.py` reads updated map, creates FCP 7 XML
   - Placements calculated based on occurrence timecodes + image duration + min gap
   - Images interleaved across configurable track count
   - XML importable into DaVinci Resolve
5. **Output:** `broll_timeline.xml` (importable) or in-Resolve placement via Lua

**State Management:**

The canonical state is `entities_map.json`. Each stage reads, optionally modifies, and writes back:

```json
{
  "entity_name": {
    "occurrences": [
      {"cue_index": 1, "timecode": "00:05:12,100", "frame": 7800},
      {"cue_index": 2, "timecode": "00:10:05,500", "frame": 15050}
    ],
    "images": [
      {
        "path": "/path/to/images/entity_name/public_domain/image1.jpg",
        "license": "public_domain",
        "source_url": "https://commons.wikimedia.org/..."
      }
    ]
  }
}
```

## Key Abstractions

**SrtCue Dataclass:**
- Purpose: Represent a single SRT subtitle block with timing and text
- Examples: `tools/srt_entities.py` lines 36-41
- Pattern: Immutable data transfer object with index, start, end, text fields

**Entities Map:**
- Purpose: Central data structure tracking entity → occurrences + images across full pipeline
- Examples: JSON file format described in `generate_broll_xml.py` documentation
- Pattern: Hierarchical dictionary updated by each stage, persisted to disk between stages

**Placement Record:**
- Purpose: Calculated clip placement for XML generation (timecode, duration, track assignment)
- Examples: `generate_broll_xml.py` lines 85-130 (placement calculation logic)
- Pattern: Dictionary with keys: frame, duration_frames, track, path, name

**LLM Provider Interface:**
- Purpose: Abstract over OpenAI vs Ollama API differences
- Examples: `tools/srt_entities.py` lines 159-190 (provider dispatch)
- Pattern: Conditional branching on provider string, same request/response structure expected

## Entry Points

**CLI Entry Point (broll.py):**
- Location: `broll.py` lines 400-540 (main function)
- Triggers: Direct invocation `python broll.py [command]`
- Responsibilities: Parse arguments, load config, dispatch to subcommand functions

**Extract Command:**
- Location: `broll.py` lines 131-172 (cmd_extract function)
- Triggers: `broll.py extract --srt FILE`
- Responsibilities: Resolve script path, build subprocess command, call `srt_entities.py`

**Download Command:**
- Location: `broll.py` lines 175-206 (cmd_download function)
- Triggers: `broll.py download --map FILE`
- Responsibilities: Build subprocess command, call `download_entities.py`

**XML Command:**
- Location: `broll.py` lines 209-255 (cmd_xml function)
- Triggers: `broll.py xml --map FILE`
- Responsibilities: Build subprocess command, call `generate_broll_xml.py`

**Pipeline Command:**
- Location: `broll.py` lines 258-353 (cmd_pipeline function)
- Triggers: `broll.py pipeline --srt FILE`
- Responsibilities: Orchestrate all three stages in sequence, stop on failure

**Direct Script Entry Points:**
- `tools/srt_entities.py` main() line 256+
- `tools/download_entities.py` main() line 340+
- `generate_broll_xml.py` main() line 280+
- `wikipedia_image_downloader.py` main() line 900+

## Error Handling

**Strategy:** Sequential fail-fast with clear error reporting

**Patterns:**
- CLI layer catches `subprocess.CalledProcessError` from failed subprocess steps, reports stage name
- Extract layer: LLM API failures return empty entity sets, script continues (resilient to API issues)
- Download layer: Individual entity download failures logged but don't block others (ThreadPoolExecutor)
- XML generation: Non-existent image paths included in XML (Resolve handles relinking)
- Environment validation: Scripts check required env vars (OPENAI_API_KEY) before processing

Examples:
- `broll.py` line 170: `except subprocess.CalledProcessError as e: print(f"Entity extraction failed: {e}", file=sys.stderr)`
- `tools/srt_entities.py` line 269-270: Return exit code 2 if no cues parsed
- `tools/download_entities.py`: Thread-safe exception handling for parallel downloads

## Cross-Cutting Concerns

**Logging:**
- Print-based to stdout/stderr (no structured logging library)
- Verbose step headers in orchestrator (`broll.py` line 112-114: "STEP: {description}")
- Progress updates during extraction (`tools/srt_entities.py` line 286: "[idx/total] Extracting...")

**Validation:**
- Path existence checks before subprocess execution (`broll.py` lines 180-182, 214-216)
- JSON structure validation in entity extraction (`tools/srt_entities.py` lines 196-207)
- Timecode format validation in SRT parsing (`tools/srt_entities.py` line 76+)
- Image path validation in XML generation (`generate_broll_xml.py` line 217)

**Authentication:**
- OpenAI: `OPENAI_API_KEY` environment variable required for provider="openai"
- Ollama: `OLLAMA_HOST` environment variable optional (defaults to http://127.0.0.1:11434)
- Wikipedia: Public API, no auth required but User-Agent expected

**Configuration:**
- YAML config file: `broll_config.yaml` (optional, any directory)
- Environment variables override config file values
- CLI flags override both
- Default config merged with provided values (`broll.py` lines 67-88)

**Timing/Rate Limiting:**
- `tools/srt_entities.py`: `--delay` parameter between LLM calls (default 0.2s)
- `wikipedia_image_downloader.py`: `--delay` between API requests (default 0.1s), retry backoff with exponential falloff
- `tools/download_entities.py`: Parallel thread pool with configurable worker count (default 4)

---

*Architecture analysis: 2026-01-25*
