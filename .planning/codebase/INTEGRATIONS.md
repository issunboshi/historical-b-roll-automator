# External Integrations

**Analysis Date:** 2026-01-25

## APIs & External Services

**Language Models (LLM):**
- OpenAI API
  - What it's used for: Entity extraction from SRT transcript cues via chat completion
  - SDK/Client: `requests` HTTP library (direct REST API calls)
  - Auth: `OPENAI_API_KEY` environment variable
  - Endpoint: `https://api.openai.com/v1/chat/completions` (configurable via `OPENAI_API_BASE`)
  - Implementation: `tools/srt_entities.py` lines 159-173
  - Models supported: `gpt-4o-mini` (default), configurable via config/CLI

- Ollama (local LLM alternative)
  - What it's used for: On-premise entity extraction alternative to OpenAI
  - SDK/Client: `requests` HTTP library
  - Host: `http://127.0.0.1:11434` (configurable via `OLLAMA_HOST` env var)
  - Endpoint: `{host}/api/chat`
  - Implementation: `tools/srt_entities.py` lines 174-188
  - Configuration: Via `--provider ollama` CLI flag

**Wikipedia API:**
- Service: Wikipedia Media API
  - What it's used for: Entity search, page metadata, image list retrieval, and image metadata
  - SDK/Client: `requests` HTTP library with custom session management
  - Auth: None (public API); User-Agent header required
  - Base URL: `https://en.wikipedia.org/w/api.php`
  - Implementation: `wikipedia_image_downloader.py` (functions: `search_wikipedia_page`, `get_page_images`, `get_content_images`, `query_image_metadata`)
  - Rate limiting: 0.1-0.3s polite delay between requests (configurable via `--delay` flag)
  - Retry strategy: Exponential backoff with jitter, max 5 retries (lines 757-798 in `wikipedia_image_downloader.py`)

## Data Storage

**Databases:**
- None; filesystem-only

**File Storage:**
- Local filesystem only
  - Downloaded images stored in entity-specific directories (e.g., `{output_dir}/{entity_name}/public_domain/image.png`)
  - Configurable output directory via `.wikipedia_image_downloader.ini` or `WIKI_IMG_OUTPUT_DIR` env var
  - Parallel downloads supported (up to 4 concurrent, configurable via `-j` flag)

**Caching:**
- None; each run re-downloads images
- Summary files: `DOWNLOAD_SUMMARY.tsv` per entity with filename, license, source URL
- Attribution tracking: `ATTRIBUTION_USED.tsv` for final license compliance

## Authentication & Identity

**Auth Provider:**
- Custom (API key-based)
  - OpenAI: Bearer token in Authorization header (`OPENAI_API_KEY`)
  - Wikipedia: Public API (User-Agent header only)
  - Ollama: None (local service)

## Monitoring & Observability

**Error Tracking:**
- None; errors logged to stderr

**Logs:**
- stdout/stderr only
  - Step indicators printed to console (e.g., "STEP: Extracting entities from transcript")
  - Entity extraction progress printed
  - Image download progress with thread-safe printing
  - Failures reported to stderr with subprocess return codes

## CI/CD & Deployment

**Hosting:**
- Not a hosted service; CLI tool
- Runs locally on user's machine or server
- Requires Python 3.13+ and external network access

**CI Pipeline:**
- None detected

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` - For OpenAI provider (required unless using Ollama)

**Optional env vars:**
- `OPENAI_API_BASE` - Custom OpenAI endpoint (defaults to https://api.openai.com/v1)
- `OLLAMA_HOST` - Ollama server address (defaults to http://127.0.0.1:11434)
- `WIKI_IMG_OUTPUT_DIR` - Wikipedia download directory override

**Secrets location:**
- Environment variables only (no .env file detected)
- User must set `OPENAI_API_KEY` before running

**Config Files:**
- `broll_config.yaml` - Pipeline settings (LLM provider, model, clip duration, track count, allow_non_pd flag)
- `.wikipedia_image_downloader.ini` - Wikipedia downloader settings (output directory)

## Webhooks & Callbacks

**Incoming:**
- None; CLI tool (no HTTP server)

**Outgoing:**
- None; no callbacks to external services

## Request Patterns & Rate Limiting

**Wikipedia API Rate Limiting:**
- Default delay: 0.1-0.3 seconds between requests (user-configurable)
- Respects Wikimedia Foundation best practices
- Retry mechanism with exponential backoff:
  - Max retries: 5
  - Backoff: 1.0 second base + jitter
  - Respects Retry-After headers if present

**OpenAI API Rate Limiting:**
- No explicit rate limiting in code (relies on OpenAI account tier)
- Temperature set to 0.2 for deterministic entity extraction
- Optional delay between LLM calls configurable via `--extract-delay` (default: 0.2s)

## Data Flow Overview

1. **Input:** SRT subtitle file (timecodes + transcript text)
2. **Extract:** LLM parses each cue, extracts people/places/concepts/events → `entities_map.json`
3. **Download:** Wikipedia API searched for each entity, images downloaded to local filesystem
4. **Generate:** XML timeline created with image clips positioned at entity timecodes
5. **Output:** FCP 7 XML importable into DaVinci Resolve with file:// URLs pointing to local images

## Security Considerations

**API Keys:**
- OpenAI key must be in environment; never committed to git
- Recommend `.gitignore` entry for `.wikipedia_image_downloader.ini`

**File URLs:**
- Generated FCP 7 XML contains `file://localhost` URLs to local image files
- Paths are URL-encoded to handle special characters (line 41-57 in `generate_broll_xml.py`)

**Wikipedia Content:**
- Filter applied to exclude non-public-domain images by default (`allow_non_pd: false`)
- License metadata tracked for compliance (`ATTRIBUTION_USED.tsv`)

---

*Integration audit: 2026-01-25*
