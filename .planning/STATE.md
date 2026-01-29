# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.
**Current focus:** Phase 2 - Search Strategy Generation

## Current Position

Phase: 2 of 5 (Search Strategy Generation)
Plan: 3 of 3 in current phase
Status: Phase complete
Last activity: 2026-01-29 — Completed 02-02-PLAN.md

Progress: [██████░░░░] 40%

## Performance Metrics

**Velocity:**
- Total plans completed: 6
- Average duration: 5.5 min
- Total execution time: 0.58 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3/3 | 24 min | 8 min |
| 2 | 3/3 | 11 min | 3.7 min |

**Recent Trend:**
- Last 5 plans: 02-02 (5 min), 02-03 (3 min), 02-01 (3 min), 01-03 (8 min), 01-02 (7 min)
- Trend: Excellent (Phase 2 averaging 3-5 min per plan)

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

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-29T14:01:09Z
Stopped at: Completed 02-02-PLAN.md (Download strategy integration)
Resume file: None
Next: Phase 2 complete - ready for Phase 3 (Priority Filtering)
