# B-Roll Finder App

## Architecture
- Main CLI: `broll.py` - orchestrates full pipeline (extract → enrich → strategies → disambiguate → download → xml)
- Tool scripts in `tools/` directory - each can run standalone or be called by broll.py
- Key tools: `download_wikipedia_images.py`, `generate_xml.py`, `download_entities.py`, `disambiguate_entities.py`
- Config: `.wikipedia_image_downloader.ini` - API keys and output_dir loaded via `config.py` into os.environ
- Optional YAML config: `broll_config.yaml` - per-role LLM provider/model overrides, default options

## Config Loading
- `import config` at top of entry points auto-loads API keys from INI file
- Tools in `tools/` need: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before `import config`
- Environment vars take precedence over INI file values

## Pipeline Checkpointing
- `.broll_checkpoint.json` tracks completed steps and SRT hash
- `--resume` continues from last incomplete step
- `--from-step <step>` forces restart from specific step
- Steps: extract, extract-visuals, enrich, summarize, merge-entities, montages, strategies, disambiguate, download, markers, xml

## Testing
- `python -m py_compile <file>` - quick syntax check
- `python broll.py pipeline --help` - verify CLI loads correctly

## API Keys (in .wikipedia_image_downloader.ini)
- ANTHROPIC_API_KEY - for disambiguation and search strategies
- OPENAI_API_KEY - for entity extraction (provider=openai)
- WIKIPEDIA_API_ACCESS_TOKEN - for authenticated Wikipedia API access (5000 req/hr vs 500 unauth)

## Data Structures
- `entities_map.json` uses a **dict keyed by entity name**, not a list:
  ```json
  {"entities": {"Garnet Wolseley": {"entity_type": "people", "priority": 0.9, "images": [...]}}}
  ```
- Image metadata is a 10-field dict: `path`, `filename`, `category`, `license_short`, `license_url`, `source_url`, `title`, `author`, `usage_terms`, `suggested_attribution`
- `LICENSE_PRIORITY` in `tools/download_entities.py`: public_domain=0, cc_by=1, cc_by_sa=2, other_cc=3, unknown=4, restricted_nonfree=5

## Download Pipeline
- `pre_download_entities.json` — snapshot of entities before the download step mutates `strategies_entities.json`
- Two skip gates prevent re-downloading: (1) `payload.get("images")` filters entities already having images in JSON, (2) `entity_dir.exists()` skips entities with existing output directories
- To re-download an entity: delete its directory from `images/` AND clear `"images"` from `strategies_entities.json` (or restore `pre_download_entities.json`)
- `--retry-failed` flag selects entities with `download_status` of `"failed"` or `"no_images"`, clears stale state, and bypasses both skip gates (entity dir + search term dir)
- Per-entity output files: `DOWNLOAD_SUMMARY.tsv` (downloaded images), `ATTRIBUTION.csv` (license metadata), `FAILED_DOWNLOADS.csv` (skipped images with reasons)

## Image Filtering (in `download_wikipedia_images.py`)
- `BLACKLIST_BASENAME_PATTERNS` — case-insensitive substring match on filenames (logos, icons, map markers, audio)
- `filter_out_ui_icons()` — regex-based secondary filter for disambiguation/protection icons
- Navbox/sister-bar containers (`.navbox`, `.sister-bar`, `.noprint`, `.portal-bar`, etc.) are decomposed before image extraction
- `/w/index.php` URLs are only extracted when they contain `File:` titles (prevents red link contamination)
- `has_image_extension()` safety net rejects non-image file titles before metadata lookup
- MediaWiki API title normalization: `query_image_metadata()` reads API `normalized`/`redirects` arrays to map canonical titles back to input titles
- See `docs/plans/image-selection-pipeline.md` for comprehensive filtering/ordering documentation

## Subcommands
- `pipeline` — full pipeline orchestration
- `extract`, `extract-visuals`, `enrich`, `summarize`, `merge-entities`, `montages`, `strategies`, `disambiguate`, `download`, `markers`, `xml` — individual steps
- `inject` — manually inject images into an entity's image list in `entities_map.json`
- `status` — show config, env vars, and tool availability

## Rate Limiting (in `download_wikipedia_images.py`)
- `MAX_RETRIES = 5` — HTTP retry attempts for 429/5xx
- `RETRY_BACKOFF_S = 0.5` — exponential backoff base for 5xx errors
- `_429_BACKOFF_S = 2.0` — exponential backoff base for 429 rate-limit responses (worst-case ~62s total wait)
- `_RateLimiter` class — thread-safe minimum-interval enforcer using `threading.Lock` + `time.monotonic()`
- Pipeline defaults: `--parallel 2` × `--download-workers 2` = 4 max concurrent downloads
- `THUMBNAIL_WIDTH` global — when >0, requests `iiurlwidth` from Wikimedia API for smaller `thumburl` downloads
- Pipeline default: `--thumbnail-width 2560` (thumbnails); standalone default: `0` (full resolution)

## Disambiguation
- `disambiguation_overrides.json` — manual entity→Wikipedia article mappings (confidence 10)
- `--interactive` flag pauses for human review of uncertain/failed entities
- `disambiguation_review.json` — entities flagged for review (confidence 4-6)
