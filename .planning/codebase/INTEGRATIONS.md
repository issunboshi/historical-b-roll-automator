# External Integrations

**Analysis Date:** 2026-01-25

## APIs & External Services

**Language Models (LLM):**
- OpenAI API
  - What it's used for: Entity extraction from SRT transcript cues (people, places, concepts, events) via GPT chat completion
  - SDK/Client: requests HTTP library (direct REST API calls, no official SDK)
  - Auth: Bearer token in Authorization header via `OPENAI_API_KEY` env var
  - Endpoint: `https://api.openai.com/v1/chat/completions` (configurable via `OPENAI_API_BASE` env var)
  - Implementation: `tools/srt_entities.py` lines 165-179
  - Models supported: `gpt-4o-mini` (default in `broll_config.yaml`), configurable via `--model` CLI flag
  - Temperature: 0.2 for deterministic extraction
  - Timeout: 60 seconds per request

- Ollama (local LLM alternative)
  - What it's used for: On-premises entity extraction alternative to OpenAI (same extraction task)
  - SDK/Client: requests HTTP library
  - Host: `http://127.0.0.1:11434` (configurable via `OLLAMA_HOST` env var)
  - Endpoint: `{host}/api/chat` (non-streaming)
  - Implementation: `tools/srt_entities.py` lines 180-194
  - Configuration: Via `--provider ollama --model <model>` CLI flags
  - Timeout: 120 seconds per request (longer than OpenAI)

**Wikipedia API:**
- Service: Wikimedia Wikipedia API
  - What it's used for: Entity search, page lookup, image discovery, and image metadata retrieval
  - SDK/Client: requests HTTP library with custom retry logic
  - Auth: None (public API); User-Agent header required (defaults to "b-roll-finder/0.1")
  - Base URL: `https://en.wikipedia.org/w/api.php`
  - Implementation: `wikipedia_image_downloader.py` multiple functions
    - `search_wikipedia_page()` - Search API query (line 60)
    - `get_page_images()` - Image enumeration from Wikipedia page (line 85)
    - `get_content_images()` - Extract images from article content area (line 115)
    - `query_image_metadata()` - Image metadata and licensing info (line 155)
  - Rate limiting:
    - Polite delay: 0.1-0.3 seconds between requests (default 0.1, configurable via `--delay` flag)
    - MediaWiki `maxlag=5` parameter to reduce server load during replication lag
  - Retry strategy: Exponential backoff with jitter
    - Max retries: 5 (configurable via `--max-retries`)
    - Base backoff: 1.0 second (configurable via `--retry-backoff`)
    - Respects Retry-After headers if present
    - Implementation: `wikipedia_image_downloader.py` lines 757-798 in `http_get()` function

**DaVinci Resolve Integration:**
- What it's used for: Timeline generation (FCP 7 XML) and media placement via Lua scripting
- Lua Script: `resolve_integration/place_broll.lua`
  - Runs within DaVinci Resolve's script environment
  - Reads `entities_map.json` with image paths and timecodes
  - Creates media pool bins and places clips on video tracks
  - Requires Resolve 18.5+ with Fusion scripting enabled
  - No external API; uses Resolve's internal Fusion/DaVinci API
- XML Output: `generate_broll_xml.py`
  - Generates FCP 7 XML timeline format (importable into Resolve via File > Import > Timeline)
  - Uses file:// URLs pointing to local image files (lines 41-57)
  - Path encoding handles special characters (URL-encodes paths)

## Data Storage

**Databases:**
- None; pure filesystem-based

**File Storage:**
- Local filesystem only
  - Downloaded images: `{output_dir}/{entity_name}/{license_category}/`
  - License categories: `public_domain/`, `cc_by/`, `cc_by_sa/`, `other_cc/`, `restricted_nonfree/`, `unknown/`
  - Summary files: `DOWNLOAD_SUMMARY.tsv` per entity with filename, license_short, license_url, source_url
  - Output directory resolution (in order):
    1. `--output PATH` CLI flag
    2. `WIKI_IMG_OUTPUT_DIR` environment variable
    3. `output_dir` setting in `.wikipedia_image_downloader.ini` config
    4. Current working directory `.`
  - Configurable via `.wikipedia_image_downloader.ini` in multiple locations:
    - `./.wikipedia_image_downloader.ini` (current dir)
    - `~/.wikipedia_image_downloader.ini` (home dir)
    - `~/.config/wikipedia_image_downloader/config.ini` (XDG config)

**Caching:**
- No persistent caching layer
- In-memory HTTP session reuse during single run (requests.Session in `wikipedia_image_downloader.py`)
- Summary files provide metadata for re-linking media
- Each run re-downloads images from Wikipedia

**State Files:**
- `entities_map.json` - Central state file containing:
  - Entity canonical names, aliases, types (person/place/concept/event)
  - Image metadata (filename, path, license, source_url)
  - Occurrence data (cue_indices, timecodes)
  - Primary entity per cue
- `DOWNLOAD_SUMMARY.tsv` - Per-entity download metadata (filename, category, license info)
- `ATTRIBUTION_USED.tsv` - License attribution for non-public-domain images used (created if `--allow-non-pd` flag set)

## Authentication & Identity

**Auth Provider:**
- Custom (API key-based with no managed identity service)
  - OpenAI: Bearer token in Authorization header; key set via `OPENAI_API_KEY` env var
  - Wikipedia: Public API; no authentication; User-Agent header identifies client
  - Ollama: No authentication; localhost-only (assumes local-only access)

**Secrets Management:**
- No secrets vault integration (Vault, AWS Secrets Manager, etc.)
- Secrets via environment variables only:
  - `OPENAI_API_KEY` - Must be set before running pipeline
  - Recommended: Never commit to version control; use `.gitignore` for `.env` files

## Monitoring & Observability

**Error Tracking:**
- None; no external error tracking service integration

**Logs:**
- stdout/stderr only (no external logging service)
  - Pipeline orchestration: Progress indicators to stdout (e.g., "STEP: Extracting entities...")
  - Entity extraction: JSON output, progress indicators to stderr
  - Image download: Thread-safe progress printing to stderr (concurrent downloads may occur)
  - Failure reporting: Subprocess exit codes reported; stderr capture on failure
  - Implementation: Thread-safe print lock in `tools/download_entities.py` lines 30-36

**Debug Output:**
- Controlled via stderr redirection
- Verbose output from subprocess calls (SRT parsing, entity extraction, image download)
- No structured logging or log aggregation

## CI/CD & Deployment

**Hosting:**
- Not a hosted service; CLI tool
- Runs locally on user's machine or on video editing workstation
- No server deployment model

**CI Pipeline:**
- None detected
- No GitHub Actions, GitLab CI, Jenkins, or similar
- No automated testing

**Deployment Method:**
- Manual script installation
- User clones repository or downloads scripts
- Run via Python directly: `python broll.py pipeline ...`
- Optional: Package as DaVinci Resolve DRFX add-on (mentioned in README but not implemented in provided code)

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` - OpenAI API authentication (required unless using `--provider ollama`)

**Optional env vars:**
- `OPENAI_API_BASE` - Custom OpenAI endpoint (defaults to https://api.openai.com/v1)
  - Useful for Azure OpenAI or other OpenAI-compatible endpoints
- `OLLAMA_HOST` - Ollama server address (defaults to http://127.0.0.1:11434)
- `WIKI_IMG_OUTPUT_DIR` - Wikipedia image download directory override

**Secrets location:**
- `.env` file (supported via python-dotenv in all scripts)
- Environment variable exports (user responsibility)
- Never in `.env.example` or version control

**Config Files:**
- `broll_config.yaml` - Pipeline configuration:
  - `images_per_entity: 4` - Number of images to download per entity
  - `image_duration_seconds: 3` - Duration each image appears on timeline
  - `min_gap_seconds: 1` - Minimum gap between clips
  - `broll_track_count: 4` - Number of video tracks for B-roll placement
  - `allow_non_pd: false` - Filter to public-domain images only
  - `llm.provider: openai` - LLM provider (openai or ollama)
  - `llm.model: gpt-4o-mini` - LLM model name
  - `fps: 25` - Timeline frame rate (default from defaults)
- `.wikipedia_image_downloader.ini` - Wikipedia downloader settings (output directory)
- Discovery: `broll_config.yaml` searched in current directory then script directory; first found wins

## Webhooks & Callbacks

**Incoming:**
- None; CLI tool (no HTTP server component)

**Outgoing:**
- None; no callbacks to external services
- Pipeline is synchronous; no async callbacks or webhooks

## Request Patterns & Rate Limiting

**Wikipedia API Rate Limiting:**
- Default delay: 0.1 seconds between requests (configurable via `--delay` flag)
- Respects Wikimedia Foundation polite use guidelines
- Retry mechanism:
  - Max retries: 5 on HTTP 429 (Too Many Requests) or 5xx errors
  - Exponential backoff: 1.0 second base (configurable via `--retry-backoff`)
  - Jitter to prevent thundering herd
  - Respects `Retry-After` header if present
  - Implementation: `wikipedia_image_downloader.py` `http_get()` function

**OpenAI API Rate Limiting:**
- No explicit rate limiting in code
- Respects OpenAI account tier rate limits (handled by API)
- No retry logic for rate limits (requests lib raises exception)
- Optional delay between entity extraction calls (not implemented in current code)

**Ollama Rate Limiting:**
- No rate limiting (local service assumed)
- 120-second timeout to allow for slow local models

## Data Flow Overview

1. **Input Phase:**
   - User provides: SRT subtitle file (timecodes + transcript text)
   - Config files: `broll_config.yaml`, `.env`

2. **Entity Extraction Phase:**
   - `tools/srt_entities.py` reads SRT file per cue
   - Calls LLM (OpenAI or Ollama) to extract entities: people, places, concepts, events
   - Outputs: `entities_map.json` with canonical names, aliases, occurrence data, timecodes

3. **Image Download Phase:**
   - `tools/download_entities.py` reads `entities_map.json`
   - For each entity, calls Wikipedia API to search and retrieve images
   - Downloads images to `{output_dir}/{entity_name}/{license_category}/`
   - Updates `entities_map.json` with image file paths and license metadata
   - Creates `DOWNLOAD_SUMMARY.tsv` per entity

4. **Timeline Generation Phase:**
   - `generate_broll_xml.py` reads `entities_map.json`
   - Creates FCP 7 XML timeline with image clips positioned at entity occurrence timecodes
   - Generates file:// URLs to local image files (URL-encoded paths)
   - Outputs: `broll_timeline.xml` (importable into DaVinci Resolve)

5. **Media Placement Phase:**
   - Option A: Resolve Python API
     - `resolve_integration/place_broll.py` reads `entities_map.json`
     - Runs within Resolve scripting environment
     - Creates media pool bins, imports images, places clips on tracks
     - Outputs: Media pool and timeline clips in active Resolve project
   - Option B: XML Import
     - User imports `broll_timeline.xml` into Resolve manually
     - Resolve creates timeline with clips at correct timecodes
     - User re-links media if file paths differ

## Security Considerations

**API Keys:**
- `OPENAI_API_KEY` must be in environment; never committed to git
- User responsible for `OPENAI_API_KEY` rotation and management
- Recommend `.gitignore` entries:
  - `.env` (environment variable file)
  - `.wikipedia_image_downloader.ini` (may contain paths)

**File URLs:**
- Generated FCP 7 XML contains `file://localhost` URLs to local image files
- Paths are URL-encoded (lines 41-57 in `generate_broll_xml.py`) to handle special characters
- Risk: URLs expose full filesystem paths in XML (readable in text editor)
- Mitigation: Keep XML files on secure, access-controlled filesystems

**Wikipedia Content:**
- Public domain filter applied by default (`allow_non_pd: false` in `broll_config.yaml`)
- License categories enforced: `public_domain/`, `cc_by/`, `cc_by_sa/`, `other_cc/`, `restricted_nonfree/`, `unknown/`
- License metadata tracked in `DOWNLOAD_SUMMARY.tsv` for compliance
- Attribution file: `ATTRIBUTION_USED.tsv` created if non-PD images used (for license compliance)

**Network Security:**
- HTTPS used for OpenAI and Wikipedia APIs
- No certificate pinning (relies on system CA bundle)
- User-Agent header identifies client for rate limiting

**Process Isolation:**
- Subprocesses spawned via subprocess.Popen
- Stdout/stderr captured for error reporting
- No shell injection protection beyond subprocess safety

---

*Integration audit: 2026-01-25*
