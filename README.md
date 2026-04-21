## B-Roll Automater

Automated b-roll generation pipeline that extracts named entities from video transcripts, downloads representative Wikipedia images, and generates FCP 7 XML timelines for import into DaVinci Resolve as picture-in-picture overlays.

### Features

- **LLM-powered entity extraction** from SRT transcripts (OpenAI or Ollama)
- **Visual element detection** — stats, quotes, processes, comparisons extracted for on-screen graphics
- **Transcript summarization** — auto-detects video era, topic, pervasive entities, and spelling-variant clusters
- **Entity deduplication** — merges transcription variants (e.g. "Pandey" / "Mangal Pandey" / "Mandel Pandey") using LLM-identified clusters and fuzzy matching
- **Montage detection** — identifies dense entity sequences suitable for rapid-fire image collages
- **Context-aware Wikipedia disambiguation** with era/chronological awareness and confidence scoring
- **LLM-generated search strategies** — contextual Wikipedia queries with era and pervasive-entity guidance
- **Priority-based filtering** — people > events > concepts > places, with mention count and position weighting
- **Frequency capping** — limits clip placements per entity to prevent timeline flooding from pervasive entities
- **Era-aware image ordering** — prioritizes historically appropriate images when year metadata is available
- **Image variety** through round-robin rotation for multi-mention entities
- **Quality-based timeline filtering**
- **FCP 7 XML output** for DaVinci Resolve import
- **Pipeline checkpointing** — resume interrupted runs from any step

---

### Requirements

- Python 3.9+ (tested with 3.11/3.12/3.13)
- Dependencies: `requests`, `beautifulsoup4`, `pydantic`, `anthropic`, `cairosvg`, `diskcache`, `tenacity`, `pyyaml`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### API Keys

Create `.wikipedia_image_downloader.ini` in the project root (or set environment variables):

```ini
[settings]
ANTHROPIC_API_KEY = sk-ant-...
OPENAI_API_KEY = sk-...
WIKIPEDIA_API_ACCESS_TOKEN = ...
output_dir = /Users/you/Downloads/WikiImages
```

Or export directly:

```bash
export OPENAI_API_KEY="sk-..."          # Entity extraction (provider=openai)
export ANTHROPIC_API_KEY="sk-ant-..."   # Search strategies, disambiguation, summarization
export WIKIPEDIA_API_ACCESS_TOKEN="..." # Authenticated Wikipedia API (5000 req/hr vs 500)
```

Config values are loaded automatically by `config.py`. Environment variables take precedence over INI file values.

---

## Quick Start

Run the full pipeline with a single command:

```bash
python broll.py pipeline --srt video.srt --subject "Documentary about the American Revolution"
```

This runs 11 steps automatically:

1. **Extract** — Parse SRT, extract named entities using LLM
2. **Extract-Visuals** — Detect stats, quotes, processes, comparisons for on-screen graphics
3. **Enrich** — Add priority scores and transcript context
4. **Summarize** — LLM-powered analysis of topic, era, pervasive entities, and entity clusters
5. **Merge-Entities** — Deduplicate transcription variants using clusters and fuzzy matching
6. **Montages** — Detect dense entity sequences for rapid-fire collage opportunities
7. **Strategies** — Generate LLM-powered Wikipedia search queries with era context
8. **Disambiguate** — Pre-compute Wikipedia disambiguation with chronological awareness
9. **Download** — Fetch images with era-aware ordering
10. **Markers** — Generate DaVinci Resolve markers
11. **XML** — Generate FCP 7 timeline with frequency capping

Output files are created in a directory named after your SRT file (or use `--output-dir`).

---

## Pipeline Options

```bash
python broll.py pipeline --srt video.srt [options]
```

### Required

| Flag | Description |
|------|-------------|
| `--srt PATH` | Path to SRT transcript |

### Common Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir, -o PATH` | SRT filename | Output directory |
| `--subject TEXT` | — | Transcript subject for entity context |
| `--fps N` | 24 | Timeline frame rate |
| `--min-priority N` | 0.5 | Skip entities below this priority (0 disables) |
| `--min-match-quality` | high | Timeline quality filter: `high`, `medium`, `low`, `none` |
| `-v, --verbose` | — | Show per-entity processing details |
| `-i, --interactive` | — | Pause for interactive review during disambiguation and download |

### Era & Quality Control

| Flag | Default | Description |
|------|---------|-------------|
| `--era TEXT` | auto-detected | Override video era (e.g. `"1857, mid-19th century India"`) |
| `--pervasive-entities TEXT` | auto-detected | Comma-separated override list of pervasive entities |
| `--max-placements N` | 3 | Max clip placements per entity on timeline |
| `--pervasive-max N` | 2 | Max placements for pervasive/background entities |
| `--coverage PCT` | — | Target timeline coverage % (0-100). Fills gaps via hybrid stretch/recycle for faceless-YT-style full coverage |
| `--stretch-threshold N` | 5.0 | Gaps shorter than this (seconds) get stretched; longer gaps get filler clips |
| `--candidates N` | 1 | Images per occurrence, stacked on consecutive tracks so you can pick the winner in the NLE. `all` (or `0`) stacks every candidate; auto-grows track count |
| `--skip-summary` | — | Skip the transcript summary step |

### Visual Elements & Montages

| Flag | Default | Description |
|------|---------|-------------|
| `--skip-visuals` | — | Skip visual element extraction |
| `--visuals-batch-size N` | 5 | Cues per LLM call for visual extraction |
| `--skip-montages` | — | Skip montage detection |
| `--montage-window N` | 8.0 | Time window (seconds) for montage density detection |
| `--montage-min-entities N` | 3 | Minimum entities for montage detection |
| `--montage-clip-duration N` | 0.6 | Duration per image in montage sequences |

### Timeline & Images

| Flag | Default | Description |
|------|---------|-------------|
| `--images-per-entity N` | 3 | Max images per entity (auto-elevated to 5 for 3+ mentions) |
| `--duration, -d N` | — | Clip duration in seconds |
| `--gap, -g N` | — | Min gap between clips in seconds |
| `--tracks, -t N` | — | Number of b-roll tracks |
| `--allow-non-pd` | — | Include non-public-domain images (PD images preferred first) |
| `--timeline-name TEXT` | — | Custom timeline name |

### Parallelism & Rate Limiting

| Flag | Default | Description |
|------|---------|-------------|
| `-j, --parallel N` | 2 | Parallel entity download subprocesses |
| `--download-workers N` | 2 | Parallel image download threads per entity |
| `--thumbnail-width N` | 2560 | Download thumbnails at this pixel width (0 = full resolution) |
| `--disambig-parallel N` | 10 | Parallel disambiguation workers |
| `--extract-delay N` | 0.2 | Delay between LLM API calls (seconds) |
| `--download-delay N` | 0.3 | Delay between Wikipedia download requests (seconds) |

**Tuning note:** Total concurrent downloads = `--parallel` × `--download-workers` (default: 4). A thread-safe rate limiter enforces a minimum interval between requests within each entity subprocess, preventing 429 (rate limit) responses from Wikimedia. If downloads fail with 429 errors, lower `--parallel` to 1 or increase `--download-delay`. With an authenticated Wikipedia API token (5000 req/hr), `--parallel 4 --download-workers 3` is safe.

**Thumbnail mode (default):** The pipeline requests thumbnails at `--thumbnail-width` pixels (default: 2560) via the Wikimedia `iiurlwidth` API parameter. Thumbnails are typically 10-20× smaller than originals, dramatically reducing download time and rate-limit pressure. Use `--thumbnail-width 0` for full-resolution originals.

### LLM & Processing

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | openai | LLM provider: `openai` or `ollama` |
| `--model NAME` | — | LLM model name |
| `--batch-size N` | 7 | Entities per LLM call for strategies |
| `--no-svg-to-png` | — | Disable SVG to PNG conversion |
| `--cache-dir PATH` | /tmp/wikipedia_cache | Wikipedia validation cache |

### Checkpointing

| Flag | Description |
|------|-------------|
| `--resume` | Resume from last completed step (uses `.broll_checkpoint.json`) |
| `--from-step STEP` | Start from specific step (ignores checkpoint) |

Valid steps: `extract`, `extract-visuals`, `enrich`, `summarize`, `merge-entities`, `montages`, `strategies`, `disambiguate`, `download`, `markers`, `xml`

---

## Individual Commands

Run steps separately for debugging or custom workflows:

```bash
# 1. Extract entities from transcript
python broll.py extract --srt video.srt --output entities_map.json

# 2. Extract visual elements (stats, quotes, processes)
python broll.py extract-visuals --srt video.srt --context "Topic of the video"

# 3. Enrich with priority and context
python broll.py enrich --map entities_map.json --srt video.srt

# 4. Generate transcript summary (topic, era, clusters)
python broll.py summarize --map enriched_entities.json --srt video.srt

# 5. Merge duplicate entities
python broll.py merge-entities --map enriched_entities.json --summary transcript_summary.json

# 6. Detect montage opportunities
python broll.py montages --entities enriched_entities.json --srt video.srt

# 7. Generate search strategies
python broll.py strategies --map merged_entities.json --video-context "Topic" --era "1850s"

# 8. Pre-compute disambiguation
python broll.py disambiguate --map strategies_entities.json -j 10

# 9. Download images
python broll.py download --map strategies_entities.json --min-priority 0.5 -v

# 10. Generate timeline XML
python broll.py xml --map strategies_entities.json --max-placements 3 --pervasive-max 2

# Utility: Inject a manually-sourced image
python broll.py inject --map entities_map.json --entity "Garnet Wolseley" --image coat_of_arms.jpg
```

### Command Reference

#### extract
| Flag | Description |
|------|-------------|
| `--srt PATH` | Path to SRT transcript (required) |
| `--output, -o PATH` | Output JSON path |
| `--output-dir PATH` | Output directory |
| `--fps N` | FPS for timecode conversion |
| `--subject TEXT` | Transcript subject for entity context |
| `--provider {openai,ollama}` | LLM provider |
| `--model NAME` | LLM model name |
| `--delay N` | Delay between LLM calls |

#### extract-visuals
| Flag | Description |
|------|-------------|
| `--srt PATH` | Path to SRT transcript (required) |
| `--output, -o PATH` | Output JSON path |
| `--output-dir PATH` | Output directory |
| `--fps N` | FPS for timecode conversion |
| `--context TEXT` | Video topic/context |
| `--provider {anthropic,openai}` | LLM provider (default: anthropic) |
| `--model NAME` | LLM model name |
| `--delay N` | Delay between LLM calls |
| `--batch-size N` | Cues per LLM call (default: 5) |
| `--no-batch` | Process cues one at a time |

#### enrich
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to entities_map.json (required) |
| `--srt PATH` | Path to original SRT file (required) |
| `--output, -o PATH` | Output JSON path |

#### summarize
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to enriched_entities.json (required) |
| `--srt PATH` | Path to original SRT file (required) |
| `--output, -o PATH` | Output JSON path |

#### merge-entities
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to enriched_entities.json (required) |
| `--summary PATH` | Path to transcript_summary.json |
| `--output, -o PATH` | Output JSON path |

#### montages
| Flag | Description |
|------|-------------|
| `--entities PATH` | Path to entities_map.json (required) |
| `--srt PATH` | Path to original SRT |
| `--output, -o PATH` | Output JSON path |
| `--window N` | Time window in seconds (default: 8.0) |
| `--min-entities N` | Minimum entities for density montage (default: 3) |

#### strategies
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to enriched/merged entities (required) |
| `--output, -o PATH` | Output JSON path |
| `--video-context TEXT` | Video topic for disambiguation |
| `--batch-size N` | Entities per LLM call (5-10) |
| `--cache-dir PATH` | Wikipedia validation cache |
| `--era TEXT` | Era/time period for search disambiguation |
| `--summary PATH` | Path to transcript_summary.json |

#### disambiguate
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to entities_map.json (required) |
| `-j, --disambig-parallel N` | Parallel workers (default: 10) |
| `--min-priority N` | Minimum priority threshold |
| `--cache-dir PATH` | Wikipedia cache directory |
| `-i, --interactive` | Interactively review uncertain disambiguations |

#### download
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to entities_map.json (required) |
| `--output-dir, -o PATH` | Output directory for images |
| `--images-per-entity N` | Max images per entity |
| `--delay N` | Delay between requests (default: 0.1) |
| `-j, --parallel N` | Parallel entity download threads (default: 4) |
| `--download-workers N` | Parallel image downloads per entity (default: 2) |
| `--thumbnail-width N` | Download thumbnails at this pixel width (0 = full resolution) |
| `--no-svg-to-png` | Disable SVG to PNG conversion |
| `--min-priority N` | Skip entities below this priority |
| `--prefer-recent` | Prioritize newer images first (auto-enabled for people entities) |
| `--no-historical-priority` | Disable older-first reordering; keep source order |
| `--era-start YEAR` | Start of era range for image ordering |
| `--era-end YEAR` | End of era range for image ordering |
| `-v, --verbose` | Show per-entity details |
| `-i, --interactive` | Interactively retry failed downloads with alternative search terms |
| `--retry-failed` | Retry entities with `download_status` in `{failed, no_images, rate_limited}` from a previous run. `rate_limited` entities are those where the Wikimedia upload CDN returned HTTP 429 twice — they're eligible for retry once the CDN cools. |

#### xml
| Flag | Description |
|------|-------------|
| `--map PATH` | Path to entities_map.json (required) |
| `--output, -o PATH` | Output XML path |
| `--output-dir PATH` | Output directory |
| `--fps N` | Timeline frame rate |
| `--duration, -d N` | Clip duration in seconds |
| `--gap, -g N` | Min gap between clips |
| `--tracks, -t N` | Number of B-roll tracks |
| `--allow-non-pd` | Include non-public-domain images; generates `.attribution.txt` for non-PD images used |
| `--timeline-name TEXT` | Custom timeline name |
| `--min-match-quality` | Quality filter: `high`, `medium`, `low`, `none` |
| `--montage-clip-duration N` | Duration per montage image (default: 0.6s) |
| `--max-placements N` | Max clip placements per entity (default: 3) |
| `--pervasive-max N` | Max placements for pervasive entities (default: 2) |
| `--summary-file PATH` | Path to transcript_summary.json |
| `--srt PATH` | Path to SRT file (required with `--coverage`) |
| `--coverage PCT` | Target timeline coverage % (0-100); fills gaps via hybrid stretch/recycle |
| `--stretch-threshold N` | Gap length (seconds) below which we stretch the previous clip instead of inserting filler (default: 5.0) |
| `--candidates N` | Images per occurrence stacked on consecutive tracks (default: 1). Use `all` / `0` to stack every candidate. With `--coverage`, gap fillers are *also* emitted as stacks from a single entity so they visually match the primary placements. |

#### inject

Manually inject images into an entity's image list. Useful for adding images sourced outside the Wikipedia pipeline (e.g., coats of arms, custom artwork).

```bash
python broll.py inject --map entities_map.json --entity "Garnet Wolseley" \
    --image /path/to/coat_of_arms.jpg --category public_domain
```

| Flag | Description |
|------|-------------|
| `--map PATH` | Path to entities_map.json (required) |
| `--entity NAME` | Entity name, must exist in map (required) |
| `--image PATH` | Path to image file, can be repeated (required) |
| `--category CAT` | License category (default: `public_domain`) |
| `--license TEXT` | License short name (e.g. "CC BY 4.0") |
| `--license-url URL` | License URL |
| `--source-url URL` | Where the image was sourced from |
| `--author TEXT` | Image author/creator |
| `--title TEXT` | Image title |

If the entity has a `download_dir`, images are copied into the appropriate license subdirectory. Images are re-sorted by license priority after injection.

#### status
```bash
python broll.py status
```
Shows configuration, environment variables, and script availability.

---

## How It Works

### Pipeline Data Flow

```
SRT transcript
  |
  v
extract -----------> entities_map.json
  |
  v
extract-visuals ----> visual_elements.json
  |
  v
enrich -------------> enriched_entities.json
  |
  v
summarize ----------> transcript_summary.json
  |                   (topic, era, pervasive entities, entity clusters)
  v
merge-entities -----> merged_entities.json
  |                   (deduplicated entities)
  v
montages -----------> montages.json
  |
  v
strategies ---------> strategies_entities.json
  |                   (era-aware search queries)
  v
disambiguate -------> strategies_entities.json (updated)
  |                   (era-aware disambiguation)
  v
download -----------> strategies_entities.json (updated) + images/
  |                   (era-aware image ordering)
  v
markers ------------> DaVinci Resolve markers
  |
  v
xml ----------------> broll_timeline.xml
                      (frequency-capped FCP 7 XML)
```

### Entity Prioritization

Entities are scored based on:
- **Type weight**: people (1.0) > events (0.9) > concepts (0.6) > places (0.3)
- **Mention count**: More mentions = higher priority (diminishing returns)
- **Position**: Early mentions (first 20%) get 1.1x boost

Entities below `--min-priority` threshold are skipped during download.

### Transcript Summarization

A single LLM call analyzes the entity list and sampled transcript cues to produce:
- **Topic**: What the video is about
- **Era**: Time period and geographic context (e.g. "1857, British colonial India")
- **Era year range**: Numeric bounds for image date filtering (e.g. [1850, 1860])
- **Pervasive entities**: Background/setting entities that are too broad for useful b-roll (e.g. "United Kingdom", "India")
- **Entity clusters**: Groups of spelling variants that should be merged (e.g. ["Mangal Pandey", "Pandey", "Mandel Pandey"])

This information flows downstream to improve search strategies, disambiguation accuracy, image ordering, and frequency capping.

### Entity Deduplication

Transcription errors often produce multiple entries for the same entity. The merge step combines them:
1. **Cluster-based merging**: Uses LLM-identified clusters from the transcript summary
2. **Fuzzy fallback**: When no summary exists, uses string similarity (threshold: 0.85) and substring containment for same-type entities
3. **Merge behavior**: Combines occurrences (deduped by timecode), unions aliases, takes max priority, concatenates contexts

### Search Strategies

Instead of naive Wikipedia searches, the LLM generates 2-3 contextual search queries per entity with era awareness:

- Entity: "Ernest Jones"
- Era: "1857, mid-19th century"
- Strategies: ["Ernest Jones Chartist", "Ernest Charles Jones 1850s", "Ernest Jones poet politician"]

For pervasive entities, the LLM redirects to contextually relevant articles:
- "United Kingdom" in an 1857 India context → "British Raj", "Company rule in India"

### Disambiguation

When Wikipedia returns multiple results:
1. Fetch summaries for top 3 candidates
2. LLM compares against transcript context **and era** — a person born after the video's era cannot be the correct match
3. Assigns confidence score (0-10)
4. Routes based on confidence:
   - **7-10**: Auto-accept, download images
   - **4-6**: Flag for review, still download
   - **0-3**: Skip entity entirely

### Frequency Capping

Prevents pervasive entities from flooding the timeline:
- **Pervasive entities** (auto-detected 10+ mentions, or from summary): max 2 placements
- **High-priority** (>= 0.8): up to 3 placements
- **Medium-priority** (0.5-0.8): up to 2 placements
- **Low-priority** (< 0.5): 1 placement
- **Single-occurrence**: always 1

When budget < total occurrences, placements are distributed: first mention (introduction), last mention, then evenly spaced through the middle.

### Era-Aware Image Ordering

When era year range is available, downloaded images are reordered:
1. Images from within the era range (sorted by closeness to midpoint)
2. Images from adjacent eras (within 50 years)
3. Other dated images
4. Unknown-year images

This prevents anachronistic images (e.g. a modern hockey team photo for "India" in an 1857 documentary).

### Image Variety

For entities mentioned 3+ times:
- Download up to 5 images (instead of 3)
- Use different images at different mentions (round-robin)
- Track which image used for which occurrence

### Quality Filtering

Timeline generation filters by match quality:
- `--min-match-quality high` — Only confident disambiguations (default)
- `--min-match-quality medium` — Include moderate confidence matches
- `--min-match-quality low` — Include weak matches
- `--min-match-quality none` — Include everything

---

## Output Files

After running the pipeline:

```
output_dir/
  entities_map.json              # Raw extracted entities
  visual_elements.json           # Stats, quotes, processes, comparisons
  enriched_entities.json         # With priority scores and context
  transcript_summary.json        # Topic, era, pervasive entities, clusters
  merged_entities.json           # Deduplicated entities
  montages.json                  # Montage/collage opportunities
  strategies_entities.json       # With search strategies, disambiguation, images
  pre_download_entities.json     # Snapshot before download step mutates strategies_entities
  broll_timeline.xml             # FCP 7 XML for DaVinci Resolve
  broll_timeline.excluded.json   # Entities excluded by quality filter
  disambiguation_review.json     # Entities flagged for human review
  disambiguation_overrides.json  # Manual entity→article overrides (if created)
  .broll_checkpoint.json         # Pipeline checkpoint state
  images/                        # Downloaded images organized by license
    Entity_Name/
      public_domain/
        image.jpg
        ATTRIBUTION.csv          # License metadata per image
      cc_by/
      ...
      DOWNLOAD_SUMMARY.tsv       # All downloaded images with license info
      FAILED_DOWNLOADS.csv       # Skipped images with skip reasons
```

### Importing to DaVinci Resolve

1. Open DaVinci Resolve
2. File > Import > Timeline > Import AAF, EDL, XML...
3. Select `broll_timeline.xml`
4. Images are referenced by absolute path — ensure the images folder is accessible

The generated FCP 7 XML uses DaVinci-compatible file references:
- Still images use `duration=1` (single frame) matching DaVinci's expectation
- File elements include `<timecode>` blocks for proper media recognition
- Consistent file IDs across bin and timeline for automatic media linking

---

## Configuration

Create `broll_config.yaml` for project defaults:

```yaml
images_per_entity: 3
allow_non_pd: false
fps: 25.0

llm:
  provider: openai
  model: gpt-4o-mini
```

Override with CLI flags or environment variables.

### LLM Role Configuration

Each pipeline step that uses an LLM has a **role name**. You can configure the provider and model per-role in `broll_config.yaml`:

```yaml
llm:
  # Global defaults
  provider: openai
  model: gpt-4o-mini

  # Per-role overrides (all optional)
  roles:
    extract:
      provider: openai
      model: gpt-4o-mini
    extract-visuals:
      provider: anthropic
      model: claude-haiku-4-5-20251001
    summarize:
      model: claude-sonnet-4-5-20250929
    strategies:
      model: claude-sonnet-4-5-20250929
    disambiguate:
      model: claude-sonnet-4-5-20250929
```

**Available roles:**

| Role | Step | Default Provider | Default Model | Constraint |
|------|------|------------------|---------------|------------|
| `extract` | Entity extraction | openai | gpt-4o-mini | — |
| `extract-visuals` | Visual element extraction | anthropic | claude-haiku-4-5-20251001 | — |
| `summarize` | Transcript summary | anthropic | claude-sonnet-4-5-20250929 | Requires Anthropic |
| `strategies` | Search strategy generation | anthropic | claude-sonnet-4-5-20250929 | Requires Anthropic |
| `disambiguate` | Wikipedia disambiguation | anthropic | claude-sonnet-4-5-20250929 | Requires Anthropic |

**Precedence order:** CLI flags (`--provider`, `--model`) > per-role config > global config > hardcoded defaults.

**Provider constraints:** The `summarize`, `strategies`, and `disambiguate` roles use Anthropic's structured outputs API (`client.beta.messages.parse`). If you configure a non-Anthropic provider for these roles, the pipeline will warn on stderr and override to Anthropic. Swapping to a different Anthropic model (e.g. Haiku) is allowed.

Use `python broll.py status` to see the resolved provider/model for each role.

---

## REST API

A FastAPI-based REST API provides remote access to the pipeline. This is useful for integrating with web UIs, remote servers, or automated workflows.

### Running the API Server

```bash
# Development (with auto-reload)
uvicorn src.api.main:app --reload --port 8001

# Production
uvicorn src.api.main:app --host 0.0.0.0 --port 8001

# Docker
docker build -t broll-finder .
docker run -p 8001:8001 \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e OPENAI_API_KEY="sk-..." \
  broll-finder
```

Interactive API docs are available at `http://localhost:8001/docs` (Swagger UI).

### API Endpoints

#### Health & Discovery

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Basic health check |
| `GET` | `/health/detailed` | Health check with environment info (API key status, Python version) |
| `GET` | `/ready` | Readiness check (verifies LLM provider credentials) |
| `GET` | `/info` | Service metadata and available endpoints |

#### Pipeline

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/pipeline/start` | Start pipeline with server-side SRT path |
| `POST` | `/api/v1/pipeline/upload` | Upload SRT file and start pipeline |
| `GET` | `/api/v1/pipeline/{id}` | Check pipeline status and progress |
| `GET` | `/api/v1/pipeline/{id}/result` | Get result with downloadable artifact metadata |
| `GET` | `/api/v1/pipeline/{id}/download/{name}` | Download individual artifact (JSON, XML) |
| `GET` | `/api/v1/pipeline/{id}/download/images` | Download all images as a zip |
| `GET` | `/api/v1/pipeline/{id}/download/all` | Download entire output as a zip |
| `DELETE` | `/api/v1/pipeline/{id}` | Cancel a running pipeline |

#### Disambiguation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/disambiguate` | Disambiguate a single entity against Wikipedia |
| `POST` | `/api/v1/search-candidates` | Search Wikipedia for candidate articles |
| `GET` | `/api/v1/candidate/{title}` | Get detailed info about a Wikipedia article |

### Usage Examples

**Start pipeline with a local SRT file:**

```bash
curl -X POST http://localhost:8001/api/v1/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"srt_path": "/path/to/video.srt"}'
```

**Upload SRT file from a remote client:**

```bash
curl -X POST http://localhost:8001/api/v1/pipeline/upload \
  -F "file=@my_video.srt"
```

**Check pipeline status:**

```bash
curl http://localhost:8001/api/v1/pipeline/{pipeline_id}
```

**Get results (artifact list with download URLs):**

```bash
curl http://localhost:8001/api/v1/pipeline/{pipeline_id}/result
```

**Download individual artifacts:**

```bash
# Download entities JSON
curl -O http://localhost:8001/api/v1/pipeline/{pipeline_id}/download/entities_map

# Download timeline XML
curl -O http://localhost:8001/api/v1/pipeline/{pipeline_id}/download/broll_timeline

# Download all images as zip
curl -O http://localhost:8001/api/v1/pipeline/{pipeline_id}/download/images

# Download everything as zip
curl -O http://localhost:8001/api/v1/pipeline/{pipeline_id}/download/all
```

**Disambiguate a single entity:**

```bash
curl -X POST http://localhost:8001/api/v1/disambiguate \
  -H "Content-Type: application/json" \
  -d '{
    "entity_name": "Ernest Jones",
    "entity_type": "people",
    "transcript_context": "the Chartist leader Ernest Jones gave speeches...",
    "video_topic": "The Indian Rebellion of 1857"
  }'
```

### Docker

The included `Dockerfile` builds a production-ready image:

```bash
docker build -t broll-finder .
docker run -p 8001:8001 \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e OPENAI_API_KEY="sk-..." \
  -v /path/to/output:/app/output \
  broll-finder
```

The container exposes port 8001 and includes a health check at `/health`.

### CORS

By default, all origins are allowed. Set `CORS_ORIGINS` environment variable to restrict:

```bash
CORS_ORIGINS="http://localhost:3000,https://myapp.com" uvicorn src.api.main:app
```

---

## Wikipedia Image Downloader (Standalone)

The underlying Wikipedia downloader can be used independently:

```bash
python3 tools/download_wikipedia_images.py "SEARCH TERM" ["ANOTHER TERM" ...]
```

### Options

- `--limit N` — Number of images to download (default: 10)
- `--output PATH` — Output directory
- `--user-agent STRING` — Custom HTTP User-Agent
- `--search-limit N` — Number of Wikipedia search results to try per query (default: 3)
- `--era-start YEAR` — Start of era range for image ordering
- `--era-end YEAR` — End of era range for image ordering

### Output Directory Resolution

1. `--output PATH` (CLI flag)
2. `WIKI_IMG_OUTPUT_DIR` environment variable
3. `output_dir` in config file
4. Current directory

### Config File Locations

- `./.wikipedia_image_downloader.ini`
- `~/.wikipedia_image_downloader.ini`
- `~/.config/wikipedia_image_downloader/config.ini`

### SVG to PNG Conversion

- Enabled by default (3000px width)
- Disable: `--no-svg-to-png`
- Change width: `--png-width 2000`
- Requires Cairo: `brew install cairo pango` (macOS)

### Rate Limiting

- `--delay SECONDS` — Politeness delay (default: 0.3)
- `--max-retries N` — HTTP retries on 429/5xx (default: 5)
- `--retry-backoff SECONDS` — Exponential backoff base for 5xx errors (default: 0.5; 429s use a longer 2.0s base)

All Wikipedia API sessions are authenticated when `WIKIPEDIA_API_ACCESS_TOKEN` is set, providing 5000 req/hr (vs 500 unauthenticated). This applies to the standalone downloader, disambiguation, and download-entities tools.

### Image Ordering

- `--prefer-recent` — Prioritize newer images first
- `--no-historical-priority` — Disable older-first reordering; keep source order
- `--era-start YEAR --era-end YEAR` — Prioritize images from within the specified era

---

## License Grouping

Images are organized by license:
- `public_domain` — Public Domain / CC0
- `cc_by` — Creative Commons Attribution
- `cc_by_sa` — Creative Commons Attribution-ShareAlike
- `other_cc` — Other Creative Commons variants
- `restricted_nonfree` — Non-free / Fair use / All rights reserved
- `unknown` — License not detected

Attribution files are created for non-public-domain images.

When `--allow-non-pd` is enabled, images are sorted by license preference (public domain first, then CC-BY, CC-BY-SA, etc.) so that PD images are used before more restrictive alternatives. The XML generator also writes a `.attribution.txt` file next to the output XML listing every non-PD image placed on the timeline, with license and suggested attribution for each.

---

## Troubleshooting

### "ANTHROPIC_API_KEY not set"

The search strategies, disambiguation, and summarization features require Claude:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Low match rate

1. Provide `--subject` with transcript context
2. Lower `--min-priority` to include more entities
3. Lower `--min-match-quality` to include uncertain matches
4. Use `--era` to help disambiguation with historical content

### Wrong-era disambiguations

For historical content, the `--era` flag helps the LLM prefer chronologically appropriate matches:
```bash
python broll.py pipeline --srt video.srt --era "1857, mid-19th century India"
```

Without `--era`, the summarize step will auto-detect the era from transcript content.

### Too many clips for common entities

Use frequency capping flags:
```bash
python broll.py pipeline --srt video.srt --max-placements 3 --pervasive-max 2
```

### Want to choose the winning image in the editor

Use `--candidates` to stack every candidate image for an entity on consecutive video tracks at the same frame. Disable/solo tracks in Resolve to pick the winner, then flatten:
```bash
python broll.py pipeline --srt video.srt --candidates all
# or a fixed cap (e.g. top 4 per entity)
python broll.py xml --map strategies_entities.json --candidates 4
```
Offset 0 (the top-ranked image) always goes to the highest track within the stack's block, so whatever's on top by default is the pipeline's best guess. Track count auto-grows to fit the largest stack unless you override `--tracks`.

### Need wall-to-wall coverage (faceless YouTube)

Use `--coverage` to fill gaps with either a held-previous-clip (short gaps) or recycled fillers from the entity pool (long gaps):
```bash
python broll.py pipeline --srt video.srt --coverage 90
# or on an existing entities map
python broll.py xml --map strategies_entities.json --srt video.srt --coverage 90
```
Tune the crossover with `--stretch-threshold` (default 5s). Pervasive entities are preferred for filler, so generic background imagery fills gaps rather than specific people or places.

When combined with `--candidates N` (or `all`), gap fillers are emitted as stacks across consecutive tracks too — one entity's candidate images form each filler stack, matching the visual grammar of the primary placements so the editor can still solo the "best" layer per filler. Filler stack height per entity is decided in `filler_stack_size()` in `tools/generate_xml.py` — tweak it to switch between permissive short-stack fillers and strict full-stack-only fillers.

Or override pervasive entities:
```bash
python broll.py pipeline --srt video.srt --pervasive-entities "United Kingdom,India"
```

### Duplicate entities from transcription errors

The merge-entities step handles this automatically. If auto-detection misses variants, re-run from summarize:
```bash
python broll.py pipeline --srt video.srt --from-step summarize
```

### Missing images in timeline

Check `broll_timeline.excluded.json` for entities filtered by quality threshold.

### Re-downloading images for specific entities

The download step skips entities that already have images in `strategies_entities.json` or an existing output directory. To force re-download:

1. Delete the entity's directory from `images/` (e.g. `rm -rf output_dir/images/Entity_Name`)
2. Either clear `"images"` from the entity in `strategies_entities.json`, or restore `pre_download_entities.json` (the pre-download snapshot)
3. Re-run: `python broll.py pipeline --srt video.srt --from-step download`

Check `FAILED_DOWNLOADS.csv` inside each entity's image directory for why specific images were skipped.

### Review flagged entities

Use `--interactive` to review uncertain disambiguations and retry failed downloads in real time:
```bash
python broll.py pipeline --srt video.srt --from-step disambiguate --interactive
```

This pauses after disambiguation and download to let you:
- Override wrong Wikipedia article matches (e.g. "Ernest Jones" -> "Ernest Charles Jones")
- Provide alternative search terms for entities with no images
- Skip entities that aren't relevant

Overrides are saved to `disambiguation_overrides.json` so they persist for future runs.

Alternatively, create overrides manually:

```json
{
  "William Dawes": "William Dawes (soldier)",
  "Ernest Jones": "Ernest Jones (Chartist)"
}
```

Then re-run from the disambiguate step:
```bash
python broll.py pipeline --srt video.srt --from-step disambiguate
```

---

## Development

Design documents in `docs/plans/` (active plans in root, completed/abandoned in `archive/`):

See [`docs/plans/README.md`](docs/plans/README.md) for full index.

Key reference: [`docs/plans/image-selection-pipeline.md`](docs/plans/image-selection-pipeline.md) — comprehensive documentation of the image discovery, filtering, ordering, and license categorization pipeline.

Project planning files in `.planning/`:
- `PROJECT.md` — Project overview and requirements
- `MILESTONES.md` — Shipped version history (v1, v2)
- `STATE.md` — Current development state
