---
phase: 03-priority-based-filtering
plan: 01
subsystem: download-filtering
tags: [priority-scoring, wikipedia-api, filtering, optimization]

# Dependency graph
requires:
  - phase: 01-priority-scoring
    provides: Priority scores and entity enrichment
  - phase: 02-search-strategy
    provides: Search strategies with validation
provides:
  - Priority-based entity filtering at download stage
  - Configurable filtering threshold via CLI
  - Verbose logging for skip diagnostics
  - Skipped entity tracking in output JSON
affects: [04-smart-image-selection, 05-production-ready]

# Tech tracking
tech-stack:
  added: []
  patterns: [guard-clause-filtering, thread-safe-filtering, dual-import-fallback]

key-files:
  created: []
  modified: [tools/download_entities.py]

key-decisions:
  - "Filter entities BEFORE parallel execution for thread safety"
  - "Default min-priority threshold of 0.5 balances quality vs coverage"
  - "Setting min-priority to 0.0 disables filtering completely"
  - "Verbose flag controls per-entity skip logging (off by default)"
  - "Skipped entities tracked in output JSON with full metadata"

patterns-established:
  - "Guard clause filtering: Early returns for type-based rules"
  - "Thread-safe filtering: Filter before parallel execution, not during"
  - "Dual import fallback: try tools.X except ImportError: import X"

# Metrics
duration: 5min
completed: 2026-01-29
---

# Phase 3 Plan 1: Priority-Based Filtering Summary

**Entity filtering at download stage with type-specific rules, reducing wasted Wikipedia API calls by skipping low-value entities**

## Performance

- **Duration:** 5 minutes
- **Started:** 2026-01-29T14:19:34Z
- **Completed:** 2026-01-29T14:25:17Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Added priority-based filtering that skips low-value entities before download
- People and events always download regardless of priority (high visual value)
- Places filter intelligently: early mentions (first 10%) and 2+ mentions always download
- Concepts require priority >= 0.7 to download (harder to visualize)
- Configurable --min-priority threshold (default 0.5, 0.0 disables filtering)
- Verbose logging (-v) shows per-entity skip decisions for debugging
- Skipped entities tracked in output JSON with metadata and skip reasons

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement filter logic and CLI arguments** - `15a21e3` (feat)
2. **Task 2: Integrate filtering with logging and JSON output** - `15d8b3f` (feat)

## Files Created/Modified
- `tools/download_entities.py` - Added should_skip_entity() function, filtering logic, CLI args (--min-priority, -v), skipped entity tracking, and Download Summary output

## Decisions Made

**Filter placement for thread safety**
- Applied filtering BEFORE parallel execution (not during) to avoid race conditions
- Built separate to_download and skipped_entities lists in single-threaded context
- Parallel executor only processes pre-filtered to_download list

**Default threshold balances quality and coverage**
- Set default min-priority to 0.5 (middle of 0.0-1.2 range)
- Low enough to keep most entities, high enough to skip obvious low-value ones
- User can adjust via --min-priority flag based on video needs

**Filtering disabled with min-priority 0**
- Setting --min-priority 0.0 completely disables filtering
- Useful for videos where every entity matters (e.g., dense educational content)
- Preserves backward compatibility with existing workflows

**Verbose logging for debugging**
- Per-entity skip messages only shown with -v flag
- Default: clean output showing only summary counts
- Verbose: shows each entity with skip reason for troubleshooting filtering rules

**Skipped entities in output JSON**
- Added "skipped" array to output JSON with full metadata
- Each entry: name, entity_type, priority, mention_count, reason
- Enables post-processing analysis of filtering effectiveness

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed plan specifications. All filtering rules work as expected across entity types.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 4 (Smart Image Selection):**
- Download stage now filters out low-value entities before API calls
- Skipped entities tracked in JSON for potential future use
- Priority scores and search strategies flow through to downloaded entities
- Clean separation: filtering happens before download, selection happens after

**Filtering effectiveness:**
- People entities (highest visual value): always downloaded
- Events (historical significance): always downloaded
- Places (contextual): early mentions and repeated mentions downloaded
- Concepts (abstract): only high-priority concepts (>= 0.7) downloaded

**No blockers.** Ready to proceed with image selection logic in Phase 4.

---
*Phase: 03-priority-based-filtering*
*Completed: 2026-01-29*
