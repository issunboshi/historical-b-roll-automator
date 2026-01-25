# Codebase Concerns

**Analysis Date:** 2026-01-25

## Tech Debt

**Duplicate imports in wikipedia_image_downloader.py:**
- Issue: `random` module is imported twice (lines 26-27)
- Files: `wikipedia_image_downloader.py`
- Impact: Minor code hygiene issue, could confuse readers about intentionality
- Fix approach: Remove one duplicate import statement

**Silent exception handling with pass statements:**
- Issue: Multiple locations catch broad `Exception` with no logging or recovery (lines 903-904, 920-921, 937-938, 967-968, 984-985, 1006-1007, 1027-1028 in `wikipedia_image_downloader.py`)
- Files: `wikipedia_image_downloader.py` (lines 903, 920, 937, 967, 984, 1006, 1027)
- Impact: Errors during CSV writing and failure recording are silently ignored, making debugging difficult when records don't persist
- Fix approach: Add logging statement or at least store error count before continuing

**Inconsistent error handling in srt_entities.py:**
- Issue: JSON parsing failure silently returns empty entity dict without logging what went wrong (line 206-207)
- Files: `tools/srt_entities.py`
- Impact: When LLM returns malformed JSON, script silently skips the entity. User has no visibility into failure count or reasons
- Fix approach: Log parse failures with line number/cue index and track statistics

**Unchecked subprocess return codes in download_entities.py:**
- Issue: Line 168-173 runs `wikipedia_image_downloader.py` but only checks for `CalledProcessError`. If the subprocess exits with code 2 but doesn't raise, silent failures occur
- Files: `tools/download_entities.py`
- Impact: Entity downloads can fail without propagating errors up to the pipeline orchestrator
- Fix approach: Always check returncode explicitly or use `check=True` (already done, but consider adding stderr capture for better diagnostics)

## Known Bugs

**SRT timecode parsing is fragile:**
- Symptoms: Multiple regex patterns attempt to parse different SRT variants (standard, VTT-like, bracketed HH:MM:SS:FF) but fall-through behavior silently skips malformed cues
- Files: `tools/srt_entities.py` (lines 66-127)
- Trigger: Non-standard SRT files with mixed timecode formats
- Workaround: Pre-validate SRT with standard converter; cues that don't match any pattern are silently dropped without warning

**Image path resolution can fail silently:**
- Symptoms: In `tools/download_entities.py` line 202, if an image's category directory doesn't exist, the fallback `entity_dir / fn` is used without verification
- Files: `tools/download_entities.py` (line 202)
- Trigger: Missing license category directories due to download interruption or corruption
- Workaround: Check if images exist before referencing them in XML generation; XML generator will skip missing files

**XML generation skips clips without warning:**
- Symptoms: In `generate_broll_xml.py` lines 354-356, if an image file doesn't exist on disk, it's silently skipped with only stderr warning
- Files: `generate_broll_xml.py` (lines 354-356)
- Trigger: Images referenced in entities_map.json but missing from filesystem (e.g., download interrupted, files moved)
- Workaround: Validate all image paths before generating XML; run download step again to fill gaps

**No validation that OPENAI_API_KEY is set before attempting calls:**
- Symptoms: `tools/srt_entities.py` retrieves env var but doesn't validate it exists before making API call (line 272)
- Files: `tools/srt_entities.py` (line 272), `broll.py` (line 398 only checks if set)
- Trigger: Running without OPENAI_API_KEY environment variable
- Workaround: Script will fail at first LLM call with "Missing Authorization header" but error is not caught or reported early

## Security Considerations

**Arbitrary file path handling from JSON input:**
- Risk: `entities_map.json` contains file paths that are used directly in `generate_broll_xml.py` without path validation. A malicious JSON could specify paths outside the intended directory
- Files: `generate_broll_xml.py` (lines 352-356 use `img_path` from JSON directly)
- Current mitigation: `os.path.exists()` check prevents reading non-existent files, but no path normalization or restriction
- Recommendations: Use `Path.resolve()` and check that all image paths are under a known base directory; reject paths with `..` or absolute paths

**Process injection via entity names:**
- Risk: Entity names extracted by LLM are passed to `subprocess.run()` in `tools/download_entities.py` (line 147)
- Files: `tools/download_entities.py` (lines 144-172)
- Current mitigation: Arguments are passed as list (not shell=True), which prevents shell injection. But very long entity names could cause issues
- Recommendations: Add reasonable length limit on entity names; validate that names don't contain null bytes or other control characters

**No rate limiting on Wikipedia API calls:**
- Risk: While retry logic exists (exponential backoff), the global `REQUEST_DELAY_S` can be set to 0 via CLI, potentially overwhelming Wikipedia servers
- Files: `wikipedia_image_downloader.py` (lines 820, 806)
- Current mitigation: Default delay of 0.3s is respectful; exponential backoff on 429 responses
- Recommendations: Enforce minimum delay (e.g., 0.05s) in validation; document Wikipedia's Terms of Service compliance

**Unauthenticated HTTP downloads without integrity checking:**
- Risk: Image files are downloaded from Wikipedia without checksum or signature verification
- Files: `wikipedia_image_downloader.py` (lines 637-643)
- Current mitigation: HTTPS connection, no specific risk since Wikipedia is trusted source
- Recommendations: Document that images come from Wikimedia Commons; consider SHA-256 verification for production use

## Performance Bottlenecks

**Sequential LLM API calls in srt_entities.py:**
- Problem: Each SRT cue makes a separate LLM request with 0.2s delay between calls (line 262, 299). For a 100-cue transcript, this takes 20+ seconds
- Files: `tools/srt_entities.py` (lines 285-295)
- Cause: Delay is hardcoded to respect LLM rate limits, but no batching of requests
- Improvement path: Implement request batching where multiple cues are processed per LLM call (if LLM supports); or use async HTTP calls instead of blocking sleep

**Image download is sequential by default:**
- Problem: Even with `--parallel 4`, entity downloads are sequential. Only images within a single entity are parallelized
- Files: `tools/download_entities.py` (lines 290-320, 321-335)
- Cause: Each entity triggers a full `wikipedia_image_downloader.py` subprocess, which is inherently sequential
- Improvement path: Batch multiple entities' image searches into single downloader run; or refactor downloader into library that can be called directly

**XML generation requires full JSON load into memory:**
- Problem: Large entities_map.json files with thousands of entities are fully loaded before processing
- Files: `generate_broll_xml.py` (line 320)
- Cause: `json.load()` reads entire file and parses; no streaming support
- Improvement path: For very large maps (10k+ entities), implement streaming JSON parser or implement pagination

**SVG to PNG conversion is CPU-bound and sequential:**
- Problem: cairosvg conversion runs for each SVG image sequentially (line 1035-1037 in `wikipedia_image_downloader.py`), blocking on I/O
- Files: `wikipedia_image_downloader.py` (lines 1034-1037)
- Cause: Conversion happens in main download loop instead of in parallel worker pool
- Improvement path: Move SVG conversion to background thread pool after download completes

## Fragile Areas

**XML track assignment algorithm:**
- Files: `generate_broll_xml.py` (lines 378-417)
- Why fragile: Track allocation is greedy - if gap_frames is miscalculated or clips are very close, many clips will be skipped (line 406). No feedback on how many were dropped
- Safe modification: Test with clips at various time intervals (1s, 2s, 5s apart); verify skipped clip count matches expectations. Add verbose logging of track allocation decisions
- Test coverage: No unit tests for track assignment; only integration test would be running with various SRT files

**LLM entity extraction reliability:**
- Files: `tools/srt_entities.py` (lines 130-207)
- Why fragile: Depends entirely on LLM returning valid JSON with expected keys. If prompt changes, model behavior changes, or API service is degraded, extraction degrades silently
- Safe modification: Add explicit validation of returned entity structure before using; log parse failures with cue index for debugging. Add fallback extraction using regex if LLM fails
- Test coverage: No testing of LLM response handling; manual tests only

**Timezone handling in datetime inference:**
- Files: `wikipedia_image_downloader.py` (line 327, 870)
- Why fragile: Uses `datetime.datetime.now().year` without timezone awareness. If running in different timezone or daylight saving transition, cutoff year calculation could be off by 1
- Safe modification: Use `datetime.datetime.now(datetime.UTC).year` or specify timezone explicitly
- Test coverage: No unit tests for year inference

**Relative path resolution in tools:**
- Files: `broll.py` (lines 91-102)
- Why fragile: Script resolution searches in `tools/` subdirectory and root directory. If called from different working directory, relative path logic breaks
- Safe modification: Always use absolute paths derived from `__file__` location. Add validation that resolved script exists before attempting execution
- Test coverage: Untested - only works if broll.py is in the expected location relative to tools

## Scaling Limits

**Single-threaded LLM processing:**
- Current capacity: ~150 cues/hour at 0.2s delay per cue (1 hour for 100-cue transcript)
- Limit: For 1000+ cue documents, processing takes 2+ hours. LLM rate limits may be hit if using free tier
- Scaling path: Implement batch API calls to OpenAI; move to async/concurrent processing with semaphore to respect rate limits

**Memory usage for large entity maps:**
- Current capacity: Entire entities_map.json is loaded into memory; a map with 1000 entities and 50 images each uses ~100MB
- Limit: For maps with 10k+ entities, memory usage could exceed available RAM on modest systems
- Scaling path: Implement streaming JSON processing; process entities in batches; use SQLite for storage instead of JSON

**Wikipedia API rate limiting:**
- Current capacity: Default 0.3s delay allows ~3300 requests/hour; processing 1000 entities at 10 images each = 10,000 API calls
- Limit: Single-threaded downloads will take 1+ hours. Wikipedia may throttle aggressive parallel requests
- Scaling path: Implement request caching; batch image metadata queries; use MediaWiki job queue for large batches

**Disk space for images:**
- Current capacity: 3 images per entity × 1000 entities × 500KB average = 1.5GB
- Limit: Large batch downloads can quickly consume disk space; no cleanup of failed/duplicate images
- Scaling path: Implement disk space monitoring; add deduplication by image hash; compress old image batches

## Dependencies at Risk

**BeautifulSoup4 for HTML parsing:**
- Risk: Parsing HTML with regex patterns as fallback is fragile. BeautifulSoup has known performance issues on large HTML documents
- Impact: If Wikipedia HTML structure changes, image extraction fails silently
- Migration plan: Monitor Wikipedia HTML changes; add unit tests for parsing with real Wikipedia page samples. Consider using lxml with CSS selectors as faster alternative

**cairosvg dependency:**
- Risk: System-level Cairo library must be installed and compatible with Python 3.13. Installation can fail on some systems
- Impact: SVG to PNG conversion silently fails; script continues but SVG files remain unconverted
- Migration plan: Make cairosvg optional and document fallback behavior; consider alternative converters (librsvg, Inkscape via subprocess)

**PyYAML for config parsing:**
- Risk: YAML parsing can execute arbitrary Python code if `yaml.load()` is used (currently safe with `yaml.safe_load()`)
- Impact: Safe load mode restricts to basic types, but future refactoring could introduce vulnerability
- Migration plan: Add linting rule to always use `yaml.safe_load()`; consider switching to TOML or JSON for config

**requests library for HTTP:**
- Risk: Depends on external HTTP client; if requests has breaking changes or security issues, pipeline breaks
- Impact: Download pipeline entirely depends on requests availability and correctness
- Migration plan: Document pinned version in requirements.txt (already done); monitor releases for security updates

## Missing Critical Features

**No duplicate image detection:**
- Problem: Multiple entities can download the same image from Wikipedia, wasting storage and timeline space
- Blocks: Can't optimize storage or avoid repeated B-roll shots

**No resume/checkpoint for pipeline:**
- Problem: If any stage fails partway through (e.g., 500 entities downloaded, then network timeout), entire pipeline must restart
- Blocks: Can't run pipeline incrementally or on unreliable networks

**No image quality metrics:**
- Problem: Downloaded images vary widely in resolution and quality; no filtering for unsuitable images
- Blocks: Can't ensure final timeline has consistent image quality

**No conflict detection for overlapping timeline placements:**
- Problem: If two entities occur at same timecode, both try to place on tracks; can exceed available tracks
- Blocks: Complex transcripts with simultaneous multiple entities will drop clips silently

**No validation of LLM entity output against available images:**
- Problem: LLM may extract entities that have no Wikipedia page or few images. Only discovered during download
- Blocks: Can't optimize entity selection upfront

## Test Coverage Gaps

**Untested SRT parsing edge cases:**
- What's not tested: Malformed timecodes, mixed formats, BOM handling, speaker line stripping
- Files: `tools/srt_entities.py` (lines 66-127)
- Risk: Non-standard SRT files silently lose cues without warning
- Priority: High - SRT is critical input format

**Untested LLM response handling:**
- What's not tested: Malformed JSON, missing keys, unexpected field types, network errors, rate limiting
- Files: `tools/srt_entities.py` (lines 130-207)
- Risk: LLM failures cascade into downstream pipeline failures
- Priority: High - LLM is external dependency

**Untested image download failure scenarios:**
- What's not tested: Network interruptions mid-download, disk full, permission errors, Wikipedia API changes
- Files: `wikipedia_image_downloader.py` (lines 637-643, 1010-1053)
- Risk: Partial downloads leave incomplete entities_map.json
- Priority: High - core functionality

**Untested XML generation with realistic data:**
- What's not tested: Very large entity counts (1000+), many simultaneous clips, missing image files, extreme timecodes
- Files: `generate_broll_xml.py` (lines 280-449)
- Risk: XML generation may fail or produce invalid output on edge cases
- Priority: Medium - affects output quality

**No integration tests for full pipeline:**
- What's not tested: End-to-end workflow with real SRT, real LLM, real downloads, real XML import
- Files: `broll.py` (lines 258-353)
- Risk: Pipeline may work in parts but fail when combined
- Priority: High - most critical user workflow

**Untested parallel download handling:**
- What's not tested: Concurrent entity downloads, thread safety of entity_map updates, race conditions on file writes
- Files: `tools/download_entities.py` (lines 310-335)
- Risk: Parallel mode may corrupt entities_map.json or lose image references
- Priority: High - parallel mode is advertised feature

---

*Concerns audit: 2026-01-25*
