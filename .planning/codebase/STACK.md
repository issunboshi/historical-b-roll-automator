# Technology Stack

**Analysis Date:** 2026-01-25

## Languages

**Primary:**
- Python 3.13+ - Core application; all pipeline scripts and CLI
- YAML - Configuration files (`broll_config.yaml`)
- XML - Output format (FCP 7 timeline XML for DaVinci Resolve)
- JSON - Data interchange (entities_map files)

## Runtime

**Environment:**
- Python 3.13.14 (detected via `python --version`)
- Virtual environment (`/.venv/`) with pinned dependencies

**Package Manager:**
- pip (standard Python package manager)
- Lockfile: `requirements.txt` - simple flat list of dependencies with version ranges

## Frameworks

**Core:**
- No traditional web framework (not a web app)
- Subprocess orchestration via Python's built-in `subprocess` module

**Data Processing:**
- BeautifulSoup4 4.12.2+ - HTML parsing (Wikipedia pages)
- PyYAML 6.0+ - YAML configuration parsing
- Requests 2.32.0+ - HTTP client for API calls

**Output Generation:**
- cairosvg 2.7.0+ - SVG to PNG conversion for image processing
- xml.etree.ElementTree (built-in) - FCP 7 XML generation
- xml.dom.minidom (built-in) - XML formatting/pretty-printing

**Testing:**
- No testing framework detected (no test files present)

**Build/Dev:**
- No build system; Python scripts run directly

## Key Dependencies

**Critical:**
- `requests` 2.32.0+ - HTTP communication with OpenAI API and Wikipedia API; implements retry logic with exponential backoff
- `beautifulsoup4` 4.12.2+ - Parsing Wikipedia HTML to extract image metadata and content
- `PyYAML` 6.0+ - Reads `broll_config.yaml` for pipeline configuration (LLM provider, image count, clip duration, etc.)
- `cairosvg` 2.7.0+ - Converts SVG images from Wikipedia to PNG (required for DaVinci Resolve compatibility)

**Infrastructure:**
- No databases, queuing systems, or caching layers
- All state stored in JSON files (`entities_map.json`)
- No external service dependencies beyond OpenAI/Ollama APIs and Wikipedia

## Configuration

**Environment:**
- `OPENAI_API_KEY` - Required for OpenAI provider (set externally)
- `OPENAI_API_BASE` - Optional; defaults to `https://api.openai.com/v1`
- `OLLAMA_HOST` - Optional; defaults to `http://127.0.0.1:11434` (for local LLM)
- `WIKI_IMG_OUTPUT_DIR` - Optional; controls where Wikipedia images are downloaded

**Build:**
- `broll_config.yaml` - Pipeline configuration (images per entity, clip duration, FPS, LLM settings)
- `.wikipedia_image_downloader.ini` - Wikipedia downloader-specific settings (output directory)

**Runtime Config Priority:**
1. Environment variables (highest priority)
2. CLI arguments
3. `broll_config.yaml` file (if present in current dir or script dir)
4. Hardcoded defaults in Python

## Platform Requirements

**Development:**
- Python 3.13+
- pip package manager
- Unix-like shell (macOS/Linux) for script execution
- OpenAI API key OR local Ollama instance for LLM

**Production:**
- Python 3.13+ runtime
- Network access to:
  - OpenAI API (`api.openai.com`) OR Ollama instance
  - Wikipedia API (`en.wikipedia.org/w/api.php`)
- Local filesystem with write permissions for output images/timelines
- DaVinci Resolve (for consuming generated FCP 7 XML)

**File Dependencies:**
- SRT (SubRip) subtitle files - Input format for transcript
- FCP 7 XML - Output format (importable into DaVinci Resolve)

---

*Stack analysis: 2026-01-25*
