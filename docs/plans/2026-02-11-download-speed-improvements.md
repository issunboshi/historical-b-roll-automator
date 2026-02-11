# Download Step Speed & Reliability Improvements

**Date:** 2026-02-11
**Status:** Implemented

## Context

The download step is very slow and fails to find images that clearly exist on Wikipedia pages. Investigation identified four root causes:

1. **Disambiguation sessions are unauthenticated** — `download_entities.py` and `disambiguate_entities.py` create bare `requests.Session()` without the Wikipedia API token, hitting the ~500 req/hr limit instead of the 5000 req/hr available with the API key
2. **Image extraction misses `<img>` tags** — `get_content_images()` only scans `<a href>` anchor tags; images rendered as bare `<img>` (without anchor wrapper) are invisible to the current extractor
3. **Search limited to 1 result** — `search_wikipedia_page()` hardcodes `srlimit=1`; if the top result is the wrong page, the entity fails with "no images found" even when the correct page has images
4. **Retry backoff is excessive** — 5 retries with 1.0s base backoff = up to 31s wasted per failed request; with authenticated access, rate limits are rare so most of this time is wasted on genuinely missing pages

## What Will Be Built

### Fix 1: Authenticate All Wikipedia Sessions

Add `build_wiki_session()` to `src/core/disambiguation.py` — a shared helper that creates a `requests.Session` with User-Agent and optional `WIKIPEDIA_API_ACCESS_TOKEN` Bearer header. Replace bare session creation in three consumer files.

**Files:**
- `src/core/disambiguation.py` — add `build_wiki_session()` after constants (line ~57)
- `tools/disambiguation.py` — import and use at line 118
- `tools/download_entities.py` — import and use at lines 684-688
- `tools/disambiguate_entities.py` — import and use at lines 490-493

### Fix 2: Extract Images from `<img>` Tags

Add a second pass to `get_content_images()` in `download_wikipedia_images.py` that scans `<img>` tags whose `src` contains `upload.wikimedia.org`. Extract filenames from:
- `data-file-name` attribute (MediaWiki metadata) if present
- URL path (handling thumb URLs: `.../thumb/.../Name.ext/NNNpx-Name.ext`)

Deduplicate against already-found titles. Filter through existing `is_probably_non_image_title()`.

**Files:**
- `tools/download_wikipedia_images.py` — extend `get_content_images()` (~line 208)

### Fix 3: Search Multiple Wikipedia Pages

Add `search_wikipedia_pages()` function returning up to N results. Refactor existing `search_wikipedia_page()` to delegate to it (backward compatible). Add `--search-limit` CLI arg (default: 3). Update `main()` to try each page result in order, stopping at the first one that yields images.

**Files:**
- `tools/download_wikipedia_images.py` — new function + refactor search + update main loop

### Fix 4: Reduce Retry Defaults

| Constant | Old | New |
|----------|-----|-----|
| `MAX_RETRIES` | 5 | 3 |
| `RETRY_BACKOFF_S` | 1.0s | 0.5s |

Max wait per request drops from 31s to 3.5s. CLI flags `--max-retries` and `--retry-backoff` remain for override.

**Files:**
- `tools/download_wikipedia_images.py` — update 4 default values (2 constants + 2 argparse)

## Files Summary

| File | Changes |
|------|---------|
| `src/core/disambiguation.py` | Add `build_wiki_session()` function |
| `tools/disambiguation.py` | Import and use `build_wiki_session()` |
| `tools/download_entities.py` | Import and use `build_wiki_session()` |
| `tools/disambiguate_entities.py` | Import and use `build_wiki_session()` |
| `tools/download_wikipedia_images.py` | `<img>` scan, multi-page search, retry defaults |
| `README.md` | Document authenticated session benefit |

## Verification

1. `python -m py_compile` on all modified files
2. `python tools/download_wikipedia_images.py --help` — shows `--search-limit`, updated retry defaults
3. `python tools/download_wikipedia_images.py "Barack Obama" --limit 3` — finds images
4. `python tools/download_wikipedia_images.py "Mercury" --limit 3` — tries multiple pages
5. `python tools/disambiguate_entities.py --help` — still works
6. Verify `WIKIPEDIA_API_ACCESS_TOKEN` is picked up by disambiguation sessions
