# Design: `--retry-failed` flag for download command

**Date:** 2026-03-01
**Status:** Approved

## Purpose

After a pipeline run, entities that hit Wikimedia CDN rate limits (HTTP 429) end up with `download_status: "failed"` in the entities JSON and 0 images on disk. Currently, re-running the download step skips these entities because their output directories already exist. The `--retry-failed` flag selects only failed entities and bypasses the directory-exists skip gate, enabling a second pass after the CDN cooldown.

## CLI interface

```bash
# Retry just the failed entities
broll.py download --map entities.json --retry-failed

# Combine with thumbnail mode for faster retry
broll.py download --map entities.json --retry-failed --thumbnail-width 2560
```

## Implementation

### `tools/download_entities.py`

1. **Argparse**: Add `--retry-failed` flag (store_true)
2. **Filter logic** (near line 709): When `--retry-failed` is set, select entities where `download_status == "failed"` instead of `not payload.get("images")`
3. **Pre-retry cleanup**: For each selected entity, clear `images` key and `download_status` from the payload dict before download
4. **`download_entity()` signature**: Add `force: bool = False` parameter
5. **Skip gate bypass** (line 423): When `force=True`, skip the `entity_dir.exists()` early-return

### `broll.py`

1. **`p_download` argparse**: Add `--retry-failed` flag
2. **`cmd_download()`**: Forward `--retry-failed` to subprocess when set

### Not changed

- `download_wikipedia_images.py` — no changes needed. The per-image `dest_path.exists()` check already prevents re-downloading images that succeeded in the first pass.
- Pipeline subcommand — retry is a manual post-pipeline action, not an automatic pipeline step.

## Edge cases

- **Partial failures** (e.g., Darwin with 2/4 images): `download_status` is `"success"`, so these are NOT retried. This is correct — they got some images. Manual re-download requires deleting the dir + clearing images.
- **Entity dir exists but empty**: The inner `search_term_dir.exists()` check counts images and only counts as success if > 0, then falls through to the next search term.
- **FAILED_DOWNLOADS.csv accumulation**: Append-only diagnostic log. New failures append on retry. Not a problem.
- **Disambiguation cache**: Already-disambiguated entities have their results cached or stored in the JSON, so retry doesn't re-run disambiguation.

## Files to modify

| File | Changes |
|------|---------|
| `tools/download_entities.py` | `--retry-failed` argparse, `force` param, filter logic, pre-retry cleanup |
| `broll.py` | `p_download` argparse, `cmd_download()` forwarding |
| `README.md` | Document `--retry-failed` flag |
| `CLAUDE.md` | Note retry feature |
