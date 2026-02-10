# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-29)

**Core value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.
**Current focus:** Post v2 features — awaiting end-to-end validation on real data

## Current Position

Phase: v2 quality improvements implemented, pending real-world validation
Plan: N/A
Status: v2 features shipped, awaiting pipeline re-run validation
Last activity: 2026-02-10 — v2 quality improvements implemented

Progress: [██████████] 100% (v2 implementation)

## v2 Summary

**Implemented:** 2026-02-10
**Phases:** 4 (frequency capping, transcript summary, entity merge, era-aware disambiguation)

**Delivered:**
- Frequency capping — limits clip placements per entity (max-placements, pervasive-max)
- Transcript summarization — auto-detects era, topic, pervasive entities, entity clusters
- Entity deduplication — merges transcription variants via LLM clusters + fuzzy matching
- Era-aware search strategies — contextual Wikipedia queries with chronological guidance
- Era-aware disambiguation — chronological fit checks reject wrong-century matches
- Era-aware image ordering — prioritizes historically appropriate images
- 2 new pipeline steps: summarize, merge-entities
- Pipeline now has 11 steps (was 9)

**Also shipped (2026-02-03 to 2026-02-05):**
- REST API layer (FastAPI + Dockerfile)
- Visual element extraction (stats, quotes, processes, comparisons)
- DaVinci Resolve marker generation
- Montage/collage detection

## v1 Summary

**Shipped:** 2026-01-29
**Phases:** 6 (14 plans)
**Duration:** 4 days
**Execution time:** 0.92 hours

**Delivered:**
- LLM-generated search strategies
- Context-aware disambiguation with confidence scoring
- Priority-based entity filtering
- Image variety (round-robin rotation)
- Quality-based timeline filtering

## Accumulated Context

### Decisions

- Frequency capping defaults: max 3 placements per entity, max 2 for pervasive
- Transcript summary uses single LLM call with ~35 sampled cues to keep cost low
- Entity merge prefers longest name as canonical (e.g. "Mangal Pandey" over "Pandey")
- All new features backward compatible — work without transcript_summary.json present

### Pending Todos

- Run full pipeline on 1857 India SRT to validate all quality improvements end-to-end
- Verify frequency capping reduces UK from 26 clips to 2, India from 16 to 2
- Verify era-aware disambiguation corrects "Ernest Jones" to Chartist (not psychoanalyst)

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-10
Stopped at: v2 implementation complete, README updated
Resume file: None
Next: End-to-end pipeline validation on real data
