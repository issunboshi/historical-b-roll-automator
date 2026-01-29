# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.
**Current focus:** Phase 2 - Search Strategy Generation

## Current Position

Phase: 2 of 5 (Search Strategy Generation)
Plan: 1 of 3 in current phase
Status: In progress
Last activity: 2026-01-29 — Completed 02-01-PLAN.md

Progress: [████░░░░░░] 27%

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 7 min
- Total execution time: 0.45 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3/3 | 24 min | 8 min |
| 2 | 1/3 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 02-01 (3 min), 01-03 (8 min), 01-02 (7 min), 01-01 (9 min)
- Trend: Improving (3-9 min range, average 7 min)

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

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-01-29T13:53:07Z
Stopped at: Completed 02-01-PLAN.md (LLM search strategy generation)
Resume file: None
