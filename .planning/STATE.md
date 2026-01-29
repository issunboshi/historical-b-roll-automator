# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.
**Current focus:** Phase 4 - Disambiguation

## Current Position

Phase: 4 of 5 (Disambiguation)
Plan: 3/TBD complete
Status: In progress
Last activity: 2026-01-29 — Completed 04-03-PLAN.md (download integration)

Progress: [████████░░] 73%

## Performance Metrics

**Velocity:**
- Total plans completed: 11
- Average duration: 4.5 min
- Total execution time: 0.83 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3/3 | 24 min | 8 min |
| 2 | 3/3 | 11 min | 3.7 min |
| 3 | 2/2 ✓ | 8 min | 4 min |
| 4 | 3/TBD | 9 min | 3 min |

**Recent Trend:**
- Last 5 plans: 04-03 (3 min), 04-02 (3 min), 04-01 (3 min), 03-02 (3 min), 03-01 (5 min)
- Trend: Excellent (consistent 3 min per plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Research completed: 5-phase structure derived from natural requirement boundaries and dependencies
- Enrichment stage: New stage 1.5 between extraction and download to augment metadata early
- Conditional disambiguation: LLM called only when multiple Wikipedia results exist (10-30% of entities)
- 01-02: Window of 3 cues (7 total) yields ~100-150 words per mention
- 01-02: Adjacent windows treated as overlapping to prevent artificial gaps
- 01-01: People entities get highest weight (1.0) for visual engagement
- 01-01: Places get lowest weight (0.3) as often contextual
- 01-01: Priority score capped at 1.2 to prevent outliers
- 01-01: Early mentions (first 20%) get 1.1x boost
- 01-03: Enrichment writes separate file (enriched_entities.json) preserving original
- 01-03: Atomic write pattern (temp file + os.replace) for safe JSON output
- 01-03: Dual import fallback for module/script execution contexts
- 02-01: Claude structured outputs (beta) eliminate 10-30% retry attempts from malformed JSON
- 02-01: Default batch size 7 entities per LLM call (research-backed balance)
- 02-01: 7-day cache TTL for Wikipedia validation (balances freshness vs API load)
- 02-01: Video context extracted from source_srt filename if not provided
- 02-01: People entities get 3 queries, all others get 2 queries
- 02-02: Stop at first successful search term (not try all) for efficiency
- 02-02: Track strategy type (best_title/query_N/fallback) in metadata
- 02-03: strategies step runs between enrich and download in pipeline sequence
- 02-03: --subject arg forwarded as --video-context to strategies step
- 02-03: strategies_entities.json replaces enriched_entities.json as input to download/XML
- 03-01: Filter entities BEFORE parallel execution for thread safety
- 03-01: Default min-priority threshold of 0.5 balances quality vs coverage
- 03-01: Setting min-priority to 0.0 disables filtering completely
- 03-01: Skipped entities tracked in output JSON with full metadata and reasons
- 03-02: CLI flags pass through from broll.py to download_entities.py subprocess
- 03-02: Both pipeline and download commands expose identical filtering flags
- 03-02: Verbose flag uses -v short form for consistency with Unix conventions
- 04-01: Disambiguation page property is empty string - check key existence not truthiness
- 04-01: Max disambiguation depth of 3 attempts prevents infinite loops
- 04-01: Confidence rubric in prompt provides reliable scoring without log probabilities
- 04-01: Skip nested disambiguation pages during link extraction
- 04-01: Single results get moderate confidence (7) not high confidence
- 04-01: CLI works without ANTHROPIC_API_KEY for search-only testing
- 04-02: Confidence 7+ auto-accepts and proceeds with download
- 04-02: Confidence 4-6 flags for review but still downloads (pragmatic approach)
- 04-02: Confidence 0-3 skips entity entirely (no download)
- 04-02: Review entries sorted by confidence (lowest first for easier review)
- 04-02: Override file ignores underscore-prefixed keys (for comments/examples)
- 04-02: Template files in output/ directory provide user documentation
- 04-03: Manual overrides in disambiguation_overrides.json take precedence over LLM
- 04-03: Video topic extracted from video_context metadata or source_srt filename
- 04-03: Review entries collected in thread-safe global list for parallel downloads
- 04-03: Disambiguation parameters passed to both sequential and parallel modes
- 04-03: Disambiguation metadata tracked in entity payload for downstream quality analysis

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-29T16:30:29Z
Stopped at: Completed 04-03-PLAN.md (download integration)
Resume file: None
Next: Continue Phase 4 (Disambiguation) — pipeline integration or next phase
