## B-Roll Automater

Automated b-roll generation pipeline that extracts named entities from video transcripts and downloads representative Wikipedia images for use as picture-in-picture overlays in DaVinci Resolve.

**v1 features:**
- LLM-powered entity extraction from SRT transcripts
- Context-aware Wikipedia disambiguation with confidence scoring
- Priority-based filtering (people > events > concepts > places)
- Image variety through round-robin rotation for multi-mention entities
- Quality-based timeline filtering
- FCP 7 XML output for DaVinci Resolve import

### Requirements

- Python 3.9+ (tested with 3.11/3.12/3.13)
- Dependencies: `requests`, `beautifulsoup4`, `pydantic`, `anthropic`, `openai`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

```bash
export OPENAI_API_KEY="sk-..."      # Required for entity extraction
export ANTHROPIC_API_KEY="sk-..."   # Required for search strategies and disambiguation
```

---

## Quick Start

Run the full pipeline with a single command:

```bash
python broll.py pipeline --srt video.srt --subject "Documentary about the American Revolution"
```

This runs 5 steps automatically:
1. **Extract** — Parse SRT, extract entities using LLM
2. **Enrich** — Add priority scores and transcript context
3. **Strategies** — Generate LLM-powered Wikipedia search queries
4. **Download** — Fetch images with disambiguation
5. **XML** — Generate FCP 7 timeline for DaVinci Resolve

Output files are created in a directory named after your SRT file.

---

## Pipeline Commands

### Full Pipeline

```bash
python broll.py pipeline --srt video.srt [options]
```

**Required:**
- `--srt PATH` — Path to SRT transcript
- `--output-dir PATH` — Output directory for all pipeline files (images, JSON, XML)

**Common options:**
- `--subject TEXT` — Topic/context for better disambiguation (recommended)
- `--fps N` — Timeline frame rate (default: from config or 24)
- `--min-priority N` — Skip entities below this priority (default: 0.5, 0 disables)
- `--min-match-quality {high,medium,low,none}` — Timeline quality filter (default: high)
- `-v, --verbose` — Show per-entity processing details

**Advanced options:**
- `--images-per-entity N` — Max images per entity (default: 3, auto-elevated to 5 for 3+ mentions)
- `--batch-size N` — Entities per LLM call for strategies (default: 7)
- `-j, --parallel N` — Parallel download threads (default: 4)
- `--duration N` — Clip duration in seconds
- `--gap N` — Minimum gap between clips
- `--tracks N` — Number of b-roll tracks
- `--allow-non-pd` — Include non-public-domain images
- `--timeline-name TEXT` — Custom name for the timeline

**Rate limiting:**
- `--extract-delay SECONDS` — Delay between LLM API calls (default: 0.2)
- `--download-delay SECONDS` — Delay between Wikipedia requests (default: 0.1)

**LLM options:**
- `--provider {openai,ollama}` — LLM provider for extraction
- `--model NAME` — LLM model name

**Processing options:**
- `--no-svg-to-png` — Disable SVG to PNG conversion
- `--cache-dir PATH` — Wikipedia validation cache directory
- `--resume` — Resume from last completed step
- `--from-step {extract,enrich,strategies,download,xml}` — Start from specific step

### Individual Steps

Run steps separately for debugging or custom workflows:

```bash
# 1. Extract entities from transcript
python broll.py extract --srt video.srt --output entities_map.json

# 2. Enrich with priority and context
python broll.py enrich --map entities_map.json --srt video.srt

# 3. Generate search strategies
python broll.py strategies --map enriched_entities.json --video-context "Topic"

# 4. Download images
python broll.py download --map strategies_entities.json --min-priority 0.5 -v

# 5. Generate timeline XML
python broll.py xml --map strategies_entities.json --min-match-quality high
```

#### Extract options
- `--srt PATH` — Path to SRT transcript (required)
- `--output, -o PATH` — Output JSON path
- `--output-dir PATH` — Output directory (creates entities_map.json inside)
- `--fps N` — FPS for timecode conversion
- `--subject TEXT` — Transcript subject for entity context
- `--provider {openai,ollama}` — LLM provider
- `--model NAME` — LLM model name
- `--delay SECONDS` — Delay between LLM calls

#### Enrich options
- `--map PATH` — Path to entities_map.json (required)
- `--srt PATH` — Path to original SRT file (required)
- `--output, -o PATH` — Output JSON path (default: enriched_entities.json)

#### Strategies options
- `--map PATH` — Path to enriched_entities.json (required)
- `--output, -o PATH` — Output JSON path
- `--video-context TEXT` — Video topic/title for disambiguation
- `--batch-size N` — Entities per LLM call (5-10)
- `--cache-dir PATH` — Wikipedia validation cache directory

#### Download options
- `--map PATH` — Path to entities_map.json (required)
- `--output-dir, -o PATH` — Output directory for downloaded images
- `--images-per-entity N` — Max images per entity
- `--delay SECONDS` — Delay between requests (default: 0.1)
- `-j, --parallel N` — Parallel download threads (default: 4)
- `--no-svg-to-png` — Disable SVG to PNG conversion
- `--min-priority N` — Skip entities below this priority
- `-v, --verbose` — Show per-entity details

#### XML options
- `--map PATH` — Path to entities_map.json (required)
- `--output, -o PATH` — Output XML path
- `--output-dir PATH` — Output directory
- `--fps N` — Timeline frame rate
- `--duration, -d N` — Clip duration in seconds
- `--gap, -g N` — Min gap between clips
- `--tracks, -t N` — Number of B-roll tracks
- `--allow-non-pd` — Include non-public-domain images
- `--timeline-name TEXT` — Name for the timeline
- `--min-match-quality {high,medium,low,none}` — Quality filter

### Check Status

```bash
python broll.py status
```

Shows configuration, environment variables, and script availability.

---

## How It Works

### Entity Prioritization

Entities are scored based on:
- **Type weight**: people (1.0) > events (0.9) > concepts (0.6) > places (0.3)
- **Mention count**: More mentions = higher priority (diminishing returns)
- **Position**: Early mentions (first 20%) get 1.1x boost

Entities below `--min-priority` threshold are skipped during download.

### Search Strategies

Instead of naive Wikipedia searches, the LLM generates 2-3 contextual search queries per entity. For example:

- Entity: "William Dawes"
- Context: American Revolution documentary
- Strategies: ["William Dawes American Revolution", "William Dawes midnight ride", "William Dawes patriot"]

### Disambiguation

When Wikipedia returns multiple results:
1. Fetch summaries for top 3 candidates
2. LLM compares against transcript context
3. Assigns confidence score (0-10)
4. Routes based on confidence:
   - **7-10**: Auto-accept, download images
   - **4-6**: Flag for review, still download
   - **0-3**: Skip entity entirely

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
video/
  entities_map.json         # Raw extracted entities
  enriched_entities.json    # With priority and context
  strategies_entities.json  # With search strategies and images
  broll_timeline.xml        # FCP 7 XML for DaVinci Resolve
  broll_timeline.excluded.json  # Entities excluded by quality filter
  disambiguation_review.json    # Entities flagged for human review
  images/                   # Downloaded images organized by license
    public_domain/
    cc_by/
    cc_by_sa/
    other_cc/
    restricted_nonfree/
    unknown/
```

### Importing to DaVinci Resolve

1. Open DaVinci Resolve
2. File → Import → Timeline → Import AAF, EDL, XML...
3. Select `broll_timeline.xml`
4. Images are referenced by path; ensure the images folder is accessible

The generated FCP 7 XML uses DaVinci-compatible file references:
- Still images use `duration=1` (single frame) matching DaVinci's expectation
- File elements include `<timecode>` blocks for proper media recognition
- Consistent file IDs across bin and timeline for automatic media linking

---

## Configuration

Create `broll_config.yaml` for project defaults:

```yaml
timeline:
  fps: 24
  duration: 4
  gap: 2
  tracks: 4

provider: openai
model: gpt-4o-mini

images_per_entity: 3
allow_non_pd: false
```

Override with CLI flags or environment variables.

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

### Output Directory Resolution

1. `--output PATH` (CLI flag)
2. `WIKI_IMG_OUTPUT_DIR` environment variable
3. `output_dir` in config file
4. Current directory

### Config File Locations

- `./.wikipedia_image_downloader.ini`
- `~/.wikipedia_image_downloader.ini`
- `~/.config/wikipedia_image_downloader/config.ini`

```ini
[settings]
output_dir = /Users/you/Downloads/WikiImages
```

### SVG to PNG Conversion

- Enabled by default (3000px width)
- Disable: `--no-svg-to-png`
- Change width: `--png-width 2000`
- Requires Cairo: `brew install cairo pango` (macOS)

### Rate Limiting

- `--delay SECONDS` — Politeness delay (default: 0.3)
- `--max-retries N` — HTTP retries on 429/5xx (default: 5)
- `--retry-backoff SECONDS` — Exponential backoff base (default: 1.0)

### Image Ordering

- `--prefer-recent` — Prioritize newer images first when year can be inferred
- `--no-historical-priority` — Disable older-first reordering; keep source order

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

---

## Troubleshooting

### "ANTHROPIC_API_KEY not set"

The search strategies and disambiguation features require Claude. Set:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Low match rate

1. Provide `--subject` with transcript context
2. Lower `--min-priority` to include more entities
3. Lower `--min-match-quality` to include uncertain matches

### Missing images in timeline

Check `broll_timeline.excluded.json` for entities filtered by quality threshold.

### Review flagged entities

Check `disambiguation_review.json` for entities that need human verification. Create `disambiguation_overrides.json` to provide manual corrections:

```json
{
  "William Dawes": "William Dawes (soldier)"
}
```

---

## Development

Project planning files in `.planning/`:
- `PROJECT.md` — Project overview and requirements
- `MILESTONES.md` — Shipped version history
- `STATE.md` — Current development state

See `.planning/milestones/` for archived roadmaps and requirements.
