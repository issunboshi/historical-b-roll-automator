## Wikipedia Page Image Downloader

Lightweight Python script that:
- Searches Wikipedia for one or more terms
- Grabs the first N images used on the page (default 10)
- Downloads originals
- Organizes them into subfolders by license: `public_domain`, `cc_by`, `cc_by_sa`, `other_cc`, `restricted_nonfree`, `unknown`
- Writes a `DOWNLOAD_SUMMARY.tsv` with license info and source URLs

### Requirements
- Python 3.9+ (tested with 3.11/3.12)
- Dependencies: `requests`, `beautifulsoup4`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Usage

```bash
python3 wikipedia_image_downloader.py "SEARCH TERM" ["ANOTHER TERM" ...]
```

#### Output directory via CLI, ENV, or config
Resolution order:
1) `--output PATH` (CLI flag, only if explicitly provided)
2) `WIKI_IMG_OUTPUT_DIR` (environment variable)
3) `output_dir` in config file
4) Current directory `.`

Environment variable example:

```bash
export WIKI_IMG_OUTPUT_DIR="/Users/you/Downloads/WikiImages"
python3 wikipedia_image_downloader.py "Barack Obama"
```

Config file locations (first found wins):
- `./.wikipedia_image_downloader.ini`
- `~/.wikipedia_image_downloader.ini`
- `~/.config/wikipedia_image_downloader/config.ini`

Config file format:

```ini
[settings]
output_dir = /Users/you/Downloads/WikiImages
```

Options:
- `--limit N` number of images to download (default: 10)
- `--output PATH` where to create the `SEARCH TERM/` folder (default: current directory)
- `--user-agent STRING` custom HTTP User-Agent (Wikimedia requests one)

Examples:

```bash
# 10 images, grouped by license, into ./Barack Obama/
python3 wikipedia_image_downloader.py "Barack Obama"

# 5 images into a custom path
python3 wikipedia_image_downloader.py "Golden Gate Bridge" --limit 5 --output ~/Downloads

# Multiple terms in one run (limit applies per term)
python3 wikipedia_image_downloader.py "Barack Obama" "Golden Gate Bridge" "New York City" --limit 8
```

### Output Layout

```
<output>/<search term>/
  public_domain/
  cc_by/
  cc_by_sa/
  other_cc/
  restricted_nonfree/
  unknown/
  DOWNLOAD_SUMMARY.tsv
```

### How images are selected
- The script parses the article HTML and collects file links within the main content area (`.mw-parser-output`), which avoids UI/status icons.
- It resolves candidates to media URLs via the API and downloads only items with `image/*` MIME types (e.g., JPEG, PNG, GIF, SVG, WebP, TIFF, BMP). Audio/video (e.g., OGG/OGA/OGV/WEBM/MP4/MP3) are ignored.
- If no content-anchored files are found, it falls back to the page’s image list while filtering out common UI/maintenance icons.

### SVG to PNG conversion
- By default, any downloaded `.svg` will be converted to a `.png` in the same folder with transparency preserved.
- Default PNG width is 3000px (aspect ratio preserved).
- You can control this behavior:
  - Disable conversion: `--no-svg-to-png`
  - Change width: `--png-width 2000`
  - If the optional system dependency Cairo is not installed, SVG conversion will be skipped automatically.
    - macOS (Homebrew): `brew install cairo pango`
    - Ubuntu/Debian: `sudo apt-get install -y libcairo2`
    - Fedora: `sudo dnf install cairo`

### Handling rate limits (HTTP 429)
- The script includes retries with exponential backoff and respects `Retry-After` headers.
- You can tune request pacing and retries:
  - `--delay SECONDS` politeness delay between requests (default: 0.3)
  - `--max-retries N` maximum HTTP retries on 429/5xx (default: 5)
  - `--retry-backoff SECONDS` base backoff used for exponential retries (default: 1.0)
- The MediaWiki `maxlag=5` parameter is used to reduce server load during replication lag.

## End-to-end B‑roll pipeline (no segments)

The pipeline consists of three steps:

1) Extract entities per cue from an SRT transcript
```bash
python tools/srt_entities.py --srt path/to/timeline.srt --provider openai --model gpt-4o-mini --out entities_map.json
```

2) Download images for the extracted entities
```bash
python tools/download_entities.py --map entities_map.json --images-per-entity 3
```
- Respects the same output directory rules as the downloader (CLI/ENV/config).
- Updates `entities_map.json` with image paths and license info.

3) Import and place images in DaVinci Resolve
```bash
# Public-domain only
python resolve_integration/place_broll.py --map entities_map.json --tracks 4 --image-duration 4 --min-gap 2

# Allow non-PD and write consolidated credits file
python resolve_integration/place_broll.py --map entities_map.json --tracks 4 --image-duration 4 --min-gap 2 --allow-non-pd
```
- Uses a fixed small number of B‑roll tracks (default 4) and interleaves placements at cue times.
- If `--allow-non-pd`, it writes an `ATTRIBUTION_USED.tsv` next to the map with credits for all non‑PD images used.

Notes:
- Run the Resolve placement script inside the Resolve scripting environment. If scripting module isn’t found, the script exits with instructions.
- The placement uses the current project’s active timeline and its FPS.
- Media Pool bins are created per entity under a root `B-Roll` bin.

### Pack as a Resolve DRFX (one‑click install)
- Build the package:
```bash
python tools/build_drfx.py --output BrollPlacer.drfx
```
- Install:
  - Double‑click `BrollPlacer.drfx`, or put it in your Resolve Support folder.
- Use in Resolve:
  - Workspace → Scripts → Utility → place_broll
  - A small dialog will prompt for `entities_map.json` and options.

`DOWNLOAD_SUMMARY.tsv` columns:
- `filename` saved file name
- `category` folder category
- `license_short` license short name from Wikimedia (if available)
- `license_url` license URL (if available)
- `source_url` original file URL

### Attribution files
- For any non-public-domain image:
  - A sidecar text file is written next to the image (e.g., `image.jpg.txt`) containing:
  - Title, Author/Creator (if available)
  - License short name and URL (if available)
  - Usage terms (if provided by Wikimedia)
  - A suggested attribution line for CC-licensed works
  - A notice for non-free or unknown licenses
  - Additionally, the script appends a row to an `ATTRIBUTION.csv` in that category folder (`cc_by`, `cc_by_sa`, `other_cc`, `restricted_nonfree`, `unknown`) with columns:
    - `filename`, `title`, `author`, `license_short`, `license_url`, `usage_terms`, `source_url`, `suggested_attribution`
- Public domain images do not receive sidecar files or CSV rows.

### License Grouping Rules (Simplified)
- `public_domain`: Public Domain / CC0
- `cc_by_sa`: Creative Commons BY-SA
- `cc_by`: Creative Commons BY
- `other_cc`: Other Creative Commons variants
- `restricted_nonfree`: Non-free/Fair use/All rights reserved/Unknown license code
- `unknown`: Anything not detected above

Note: Wikimedia `extmetadata` varies by file. Always review the summary file and file pages to confirm reuse terms.

### Notes
- This script uses Wikipedia's API (`action=parse` and `imageinfo` with `extmetadata`) and downloads original-resolution files when available.
- Be considerate: avoid very high request volumes; a small delay is included between metadata calls.
- Provide a descriptive `--user-agent` string if you publish or share the tool.


