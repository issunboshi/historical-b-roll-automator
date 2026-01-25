# Technology Stack

**Analysis Date:** 2026-01-25

## Languages

**Primary:**
- Python 3.13.3 - Core application; all pipeline scripts and CLI
- Lua 5.1 - DaVinci Resolve scripting (`resolve_integration/place_broll.lua`)
- YAML - Configuration files (`broll_config.yaml`)
- XML - Output format (FCP 7 timeline XML for DaVinci Resolve)
- JSON - Data interchange (entities_map files, test data)

## Runtime

**Environment:**
- Python 3.13.3 (specified in `.python-version`)
- Lua 5.1 (embedded in DaVinci Resolve for scripting)
- Virtual environment support (common practice, no `.venv/` committed)

**Package Manager:**
- pip (standard Python package manager)
- Lockfile: `requirements.txt` - pinned version ranges for all dependencies

## Frameworks

**Core:**
- No traditional frameworks (not a web app)
- subprocess (built-in) - orchestration of pipeline steps in `broll.py`
- argparse (built-in) - CLI argument parsing across all entry points

**Data Processing:**
- requests 2.32.0+ - HTTP client for OpenAI API, Ollama, and Wikipedia API calls
- beautifulsoup4 4.12.2+ - HTML parsing for Wikipedia page content and image extraction
- PyYAML 6.0+ - YAML configuration file parsing (`broll_config.yaml`)
- python-dotenv 1.0.0+ - Environment variable loading from `.env` files

**Output Generation:**
- cairosvg 2.7.0+ - SVG to PNG conversion (optional; gracefully degraded if Cairo not installed)
- xml.etree.ElementTree (built-in) - FCP 7 XML generation in `generate_broll_xml.py`
- xml.dom.minidom (built-in) - XML pretty-printing and formatting
- csv (built-in) - TSV/CSV reading for license metadata (`DOWNLOAD_SUMMARY.tsv`)
- json (built-in) - Entities map serialization/deserialization
- pathlib (built-in) - Cross-platform path handling

**Testing:**
- No testing framework detected (no test files; manual testing only)

**Build/Dev:**
- No build system; Python scripts execute directly
- Manual testing via CLI commands

## Key Dependencies

**Critical:**
- `requests` 2.32.0+ - HTTP communication with OpenAI API (`tools/srt_entities.py`), Ollama, and Wikipedia API (`wikipedia_image_downloader.py`); implements exponential backoff retry logic
- `beautifulsoup4` 4.12.2+ - HTML parsing of Wikipedia pages to extract images and metadata
- `PyYAML` 6.0+ - Configuration management via `broll_config.yaml` (LLM provider, image count, clip duration, FPS, track count, allow_non_pd flag)
- `python-dotenv` 1.0.0+ - Environment variable injection from `.env` files for API keys

**Infrastructure:**
- `cairosvg` 2.7.0+ - Optional but recommended for SVG to PNG conversion; gracefully skips if system Cairo not installed
- No databases, caches, or external state stores
- No message queues or job runners
- File-based state: `entities_map.json`, `DOWNLOAD_SUMMARY.tsv`, `ATTRIBUTION_USED.tsv`

## Configuration

**Environment:**
- `.env` file support via python-dotenv (for `OPENAI_API_KEY`, `OPENAI_API_BASE`, `OLLAMA_HOST`, `WIKI_IMG_OUTPUT_DIR`)
- `broll_config.yaml` - Pipeline parameters (images_per_entity, image_duration_seconds, min_gap_seconds, broll_track_count, allow_non_pd, fps, llm provider/model)
- `.wikipedia_image_downloader.ini` - Wikipedia downloader output directory setting

**Required env vars:**
- `OPENAI_API_KEY` - OpenAI API authentication (unless using Ollama)

**Optional env vars:**
- `OPENAI_API_BASE` - OpenAI endpoint override (defaults to https://api.openai.com/v1)
- `OLLAMA_HOST` - Ollama endpoint (defaults to http://127.0.0.1:11434)
- `WIKI_IMG_OUTPUT_DIR` - Wikipedia image download output directory

**Build:**
- Configuration priority order:
  1. CLI flags (highest)
  2. `broll_config.yaml` (if present in cwd or script dir)
  3. Hardcoded defaults in Python code

## Platform Requirements

**Development:**
- Python 3.9+ (3.13.3 recommended; tested with 3.11/3.12)
- pip and venv
- System packages for image conversion:
  - macOS (Homebrew): `brew install cairo pango`
  - Ubuntu/Debian: `apt-get install libcairo2`
  - Fedora: `dnf install cairo`
- OpenAI API key OR local Ollama instance running on localhost:11434
- Network access to:
  - https://en.wikipedia.org/w/api.php
  - https://api.openai.com/v1 (or custom OPENAI_API_BASE)
  - Wikipedia image CDNs (commons.wikimedia.org, upload.wikimedia.org)

**Production:**
- Python 3.13+ runtime environment
- DaVinci Resolve 18.5+ (for FCP 7 XML import and Lua script execution)
- Filesystem with write permissions for image storage
- Network access to OpenAI/Ollama and Wikipedia APIs
- SRT subtitle files as input format
- FCP 7 XML as intermediate/output format

**File Formats:**
- Input: SRT (SubRip subtitle format)
- Intermediate: JSON (`entities_map.json` with entity metadata)
- Output: FCP 7 XML (importable into DaVinci Resolve)
- Metadata: TSV files for license tracking and attribution

---

*Stack analysis: 2026-01-25*
