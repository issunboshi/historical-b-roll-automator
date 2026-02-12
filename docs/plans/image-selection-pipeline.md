# Image Selection Pipeline

How images are discovered, filtered, ordered, and placed throughout the B-Roll Finder pipeline.

---

## 1. Search Strategy Generation

**File:** `tools/generate_search_strategies.py`

Claude Sonnet generates 2–3 Wikipedia search queries per entity:

- **People** → 3 queries (full name, common variation, role-based)
- **Other types** → 2 queries
- Queries ordered by confidence (most likely first)

The LLM receives video context and era information for disambiguation. Pervasive/background entities get contextually-relevant searches instead of generic ones (e.g. "United Kingdom" in an 1857 India context → "British Raj" or "Company rule in India").

Each generated `best_title` and query is validated against Wikipedia via `WikipediaValidator` with a 7-day disk cache to confirm the article exists.

---

## 2. Wikipedia Image Discovery

**File:** `tools/download_wikipedia_images.py`

Two methods, tried in sequence:

### Method A: Content-Anchored Images (preferred)

`get_content_images()` parses the article HTML and extracts images from within `.mw-parser-output` — the article body only. This finds `<a>` tags linking to `/wiki/File:` URLs and `<img>` tags from `upload.wikimedia.org`. Images return in article-appearance order (infobox portrait first for people, for example).

### Method B: Page-Level Images (fallback)

`get_page_images()` uses the MediaWiki `parse/images` API. Returns all images on the page including navigation and sidebar. Used only when content-anchored discovery finds nothing.

### Selection logic

```
1. Try get_content_images()
2. If empty → filter_out_ui_icons(get_page_images())
3. If still empty → try next search result
```

---

## 3. Filtering Pipeline

Images pass through multiple filtering stages before download:

### Stage 1: Basename Blacklist

`BLACKLIST_BASENAME_PATTERNS` (line 50) — case-insensitive substring match on the filename:

| Category | Examples |
|----------|----------|
| Wikimedia logos | `wikisource-logo`, `commons-logo`, `wikipedia-logo` |
| UI/maintenance icons | `question_book`, `padlock`, `lock-`, `ambox`, `edit-clear` |
| Map markers | `red_pog`, `blue_pog`, `location_dot`, `map_marker` |
| Audio icons | `speaker_icon` |

A second regex-based blacklist (`filter_out_ui_icons`, line 302) catches additional patterns like `semi-protection`, `disambig`, `magnify`, and all Wikimedia project logos.

### Stage 2: Non-Image File Extensions

`is_probably_non_image_title()` skips files with audio/video extensions: `.ogg`, `.oga`, `.opus`, `.mp3`, `.wav`, `.ogv`, `.webm`, `.mp4`, etc.

### Stage 3: MIME Type

Requires `mime.startswith("image/")`. Anything else is logged and skipped.

### Stage 4: Symbolic SVG Detection

SVGs matching these patterns are skipped (they render poorly at timeline scale):

- Contains "flag" in title/name/description
- Contains "coat of arms" variants (`coat_of_arms`, `coat-of-arms`)
- Contains "signature" or "autograph"

Only applies when MIME is `image/svg+xml`.

### Stage 5: SVG–PNG Deduplication

When both an SVG and PNG version exist with the same basename, only the PNG is kept. This avoids downloading redundant representations and ensures the raster version (preferred for timeline use) is used.

All skipped images are logged to `FAILED_DOWNLOADS.csv` with the skip reason.

---

## 4. License Categorization

**Function:** `categorize_license()` in `download_wikipedia_images.py`

Six categories, ordered by preference:

| Priority | Category | Detection |
|----------|----------|-----------|
| 0 (best) | `public_domain` | "public domain" in license, or code in `{pd, cc-zero}`, or "cc0" |
| 1 | `cc_by` | Code starts with `cc-by` and "sa" not in license |
| 2 | `cc_by_sa` | Code starts with `cc-by-sa` or "cc by-sa" |
| 3 | `other_cc` | Other `cc-` codes or "attribution required" |
| 4 | `unknown` | License information missing or unclear |
| 5 (worst) | `restricted_nonfree` | "nonfree", "fair use", or code in `{unknown, arr}` |

Downloaded images are organized into subdirectories by category:
```
output_dir/Entity_Name/
├── public_domain/
│   ├── image1.jpg
│   └── ATTRIBUTION.csv
├── cc_by/
├── cc_by_sa/
└── DOWNLOAD_SUMMARY.tsv
```

---

## 5. Image Ordering

**File:** `tools/download_wikipedia_images.py`

After discovery and filtering, images are reordered before download. The ordering mode depends on entity type and CLI flags.

### Historical Priority (default)

**Without era context:**

| Group | Images | Sort within group |
|-------|--------|-------------------|
| 0 (first) | Older images (year ≤ current − 30) | Year ascending (oldest first) |
| 1 | Recent images (year > current − 30) | Year ascending |
| 2 (last) | Unknown-year images | Original order |

**With era context** (`--era-start`, `--era-end`):

| Group | Images | Sort within group |
|-------|--------|-------------------|
| 0 (first) | Within era range | Closeness to era midpoint |
| 1 | Adjacent era (±50 years) | Closeness to midpoint |
| 2 | Other dated images | Closeness to midpoint |
| 3 (last) | Unknown-year images | Original order |

### Recent Priority (`--prefer-recent`)

Used for **people** entities. Newer images appear first:

| Group | Images | Sort |
|-------|--------|------|
| 0 | Known-year images | Year descending (newest first) |
| 1 | Unknown-year images | Original order |

### Year Inference

`infer_image_year()` extracts the year from metadata fields in priority order:
DateTimeOriginal → DateTime → DateTimeDigitized → Date → ObjectName → ImageDescription → file title.

Returns the minimum (oldest) year found, or `None`.

---

## 6. Entity-Type-Specific Logic

### Priority Weights

**File:** `tools/enrich_entities.py`

```python
TYPE_WEIGHTS = {
    "people": 1.0,           # Faces are engaging
    "events": 0.9,           # Strong visual potential
    "organizations": 0.7,    # Moderate visual interest
    "concepts": 0.6,         # Harder to visualize
    "places": 0.3,           # Often just context/setting
}
```

### Download Thresholds

**File:** `tools/download_entities.py`

| Type | Rule |
|------|------|
| People | Always download |
| Events | Always download |
| Places | Download if: first mention ≤ 10% into transcript, OR ≥ 2 mentions, OR priority ≥ threshold |
| Concepts | Requires priority ≥ 0.7 |
| Default | Requires priority ≥ `--min-priority` |

### Ordering Overrides

| Condition | Ordering |
|-----------|----------|
| `entity_type == "people"` | `--prefer-recent` (newer images first) |
| Entity name contains a year | `--no-historical-priority` (source order) |
| All other types | Default historical priority |

### Multi-Mention Boost

Entities with ≥ 3 mentions get up to 5 images downloaded (instead of the default `--images-per-entity`).

---

## 7. Disambiguation Impact

**File:** `tools/disambiguate_entities.py`

Disambiguation runs before download to ensure the correct Wikipedia article is targeted.

| Confidence | Action | Effect on search |
|------------|--------|------------------|
| ≥ 7 | `download` | Search ONLY the disambiguated article |
| 4–6 | `flag_and_download` | Try disambiguated article first, then fallback queries |
| < 4 | `skip` | Entity not downloaded at all |

Manual overrides (`disambiguation_overrides.json`) can force an entity to a specific Wikipedia article with confidence 10.

Interactive review (`--interactive`) presents uncertain/failed entities for human correction after the parallel disambiguation pass.

---

## 8. Montage vs Single-Image

### Detection

**File:** `tools/detect_montages.py`

Three montage triggers:

| Type | Trigger | Image count |
|------|---------|-------------|
| Density | ≥ 3 unique entities within 8s window | min(unique_entities, 5) |
| Sweep event | Entity matches SWEEP_EVENTS list (wars, revolutions, eras) | 4 |
| Enumeration | Patterns like "leaders like X, Y, Z" | Based on list length |

### Timeline Placement

**File:** `tools/generate_xml.py`

**Montage entities** get a rapid image sequence:
- Each image gets `montage_clip_duration` (default 0.6s)
- Images placed back-to-back: `frame + (index × montage_clip_frames)`
- Named: `"Entity Name - montage 1/4"`, `"Entity Name - montage 2/4"`, etc.

**Non-montage entities** get a single image per occurrence:
- Standard clip duration (default 4.0s)
- Images rotate round-robin: `images[occurrence_index % len(images)]`

Montage entities also get more images downloaded — `max(images_per_entity, montage_image_count)`.

---

## 9. Harvest → entities_map.json → XML Flow

### Harvest Phase

**Function:** `harvest_images()` in `tools/download_entities.py`

After download completes for each entity:

1. Read `DOWNLOAD_SUMMARY.tsv` (one row per downloaded image: filename, category, license metadata)
2. Skip raw SVGs (prefer converted PNG if it exists)
3. Deduplicate by absolute file path
4. Enrich with `ATTRIBUTION.csv` data (title, author, usage_terms, suggested_attribution)
5. Sort by `LICENSE_PRIORITY` (stable sort preserves ordering within each license tier)

Output: 10-field image metadata dict:
```json
{
  "path": "/absolute/path/to/image.jpg",
  "filename": "image.jpg",
  "category": "public_domain",
  "license_short": "Public Domain",
  "license_url": "...",
  "source_url": "https://commons.wikimedia.org/...",
  "title": "Portrait of ...",
  "author": "Artist Name",
  "usage_terms": "...",
  "suggested_attribution": "..."
}
```

### entities_map.json Structure

```json
{
  "entities": {
    "Entity Name": {
      "entity_type": "people",
      "priority": 0.9,
      "images": [ /* array of 10-field dicts from harvest */ ],
      "occurrences": [ { "timecode": "00:01:23,456", ... } ],
      "disambiguation": { "wikipedia_title": "...", "confidence": 8 },
      "download_dir": "/path/to/Entity_Name"
    }
  }
}
```

### XML Generation

**File:** `tools/generate_xml.py`

1. Load entities_map.json
2. For each entity with images and occurrences:
   - Filter images by license (PD-only unless `--allow-non-pd`)
   - Calculate placement budget (frequency capping)
   - Select which occurrences to place
   - Generate FCP 7 XML clip elements
3. Write `.attribution.txt` if non-PD images used

---

## 10. Frequency Capping and Pervasive Entities

**Function:** `calculate_placement_budgets()` in `tools/generate_xml.py`

Each entity gets a budget limiting how many times it appears on the timeline:

| Condition | Budget |
|-----------|--------|
| Single mention | 1 |
| Pervasive entity OR ≥ 10 mentions | min(`pervasive_max`, mentions) |
| Priority ≥ 0.8 | min(`max_placements`, mentions) |
| Priority 0.5–0.79 | min(`max_placements − 1`, mentions) |
| Priority < 0.5 | 1 |

Default values: `max_placements=3`, `pervasive_max=2`.

**Pervasive entities** are identified from:
- `transcript_summary.json["pervasive_entities"]` (LLM-identified)
- Auto-detected if ≥ 10 mentions

### Occurrence Selection

**Function:** `select_occurrences()`

Given the budget, selects chronologically-distributed occurrences:
1. Always include the **first** occurrence (entity introduction)
2. Include the **last** if budget ≥ 2 (conclusion/callback)
3. Fill remaining budget with **evenly-spaced** middle occurrences

---

## 11. allow-non-pd Filtering at XML Generation

**Default behavior** (no flag): Only `public_domain` images reach the timeline.

```python
# generate_xml.py line 510-513
if args.allow_non_pd:
    filtered_images = images
else:
    filtered_images = [img for img in images if img.get('category') == 'public_domain']
```

**With `--allow-non-pd`:**
- All license categories used on timeline
- A `.attribution.txt` file is generated listing non-PD images used, with their license info and suggested attribution

**Note:** All license categories are always **downloaded** regardless of this flag. The filtering happens only at XML generation time, so you can regenerate the XML with different license policies without re-downloading.

---

## Pipeline Summary

```
SRT transcript
    │
    ▼
[1] Extract entities (LLM) ──────────── entities_map.json
    │
    ▼
[2] Enrich (priority scores, TYPE_WEIGHTS)
    │
    ▼
[3] Search strategies (LLM) ─────────── 2-3 Wikipedia queries per entity
    │
    ▼
[4] Disambiguate (LLM + Wikipedia) ──── confidence scores, article mapping
    │
    ▼
[5] Download
    ├── Discovery: content-anchored → page-level fallback
    ├── Filtering: blacklist → extension → MIME → symbolic SVG → SVG dedup
    ├── Ordering: era-aware historical | prefer-recent (people) | source order
    ├── License categorization → per-category subdirectories
    └── harvest_images() → LICENSE_PRIORITY sort → entities_map.json
    │
    ▼
[6] XML generation
    ├── License filter: PD-only (default) or all (--allow-non-pd)
    ├── Frequency capping: placement budgets per entity
    ├── Occurrence selection: first + last + evenly-spaced middle
    ├── Montage: rapid sequence (0.6s/image) vs single-image (4.0s)
    └── FCP 7 XML → DaVinci Resolve import
```

---

## Manual Image Injection

The `inject` subcommand bypasses the download pipeline and writes directly to `entities_map.json`:

```bash
python broll.py inject --map entities_map.json --entity "Garnet Wolseley" \
    --image /path/to/coat_of_arms.jpg --category public_domain
```

Injected images use the same 10-field metadata format and are re-sorted by `LICENSE_PRIORITY` after insertion. If the entity has a `download_dir`, images are copied into the appropriate license subdirectory.
