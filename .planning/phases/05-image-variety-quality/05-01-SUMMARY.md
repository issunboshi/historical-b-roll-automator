---
phase: 05-image-variety-quality
plan: 01
subsystem: api
tags: [python, image-download, wikipedia, variety]

# Dependency graph
requires:
  - phase: 04-disambiguation
    provides: "Disambiguation logic and metadata tracking in entity payloads"
provides:
  - "Dynamic image count: 5 images for entities with 3+ mentions, 3 for others"
  - "Transparent logging of image count decisions and elevated download statistics"
affects: [05-image-variety-quality, timeline-filtering]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Mention-based image variety strategy", "Transparent download statistics"]

key-files:
  created: []
  modified: ["tools/download_entities.py"]

key-decisions:
  - "5 images for entities with 3+ mentions provides adequate variety"
  - "Threshold of 3 mentions balances download volume with variety needs"
  - "Elevated count message shows regardless of verbose flag (actionable information)"

patterns-established:
  - "Dynamic resource allocation based on entity usage frequency"
  - "Transparent statistics tracking for operational visibility"

# Metrics
duration: 2min
completed: 2026-01-29
---

# Phase 5 Plan 01: Dynamic Image Count Summary

**Entities with 3+ mentions now download 5 images for variety, with transparent logging and statistics tracking**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-29T17:05:40Z
- **Completed:** 2026-01-29T17:07:23Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Dynamic image count calculation based on mention frequency (3+ mentions = 5 images)
- Clear console output showing when elevated image count is used
- Download summary includes count of entities with elevated images
- Both sequential and parallel execution modes support dynamic counts

## Task Commits

Each task was committed atomically:

1. **Task 1: Add dynamic image count calculation** - `9413de0` (feat)
2. **Task 2: Add verbose logging for image count decisions** - `71db068` (feat)

## Files Created/Modified
- `tools/download_entities.py` - Added mention_count parameter, effective_images calculation, elevated count tracking, and summary statistics

## Decisions Made
- **5 images for 3+ mentions:** Research (VAR-03) showed entities with multiple mentions need more images for variety during timeline playback
- **Threshold of 3 mentions:** Balances download volume with variety needs - common entities get more options
- **Always show elevated message:** Multi-mention logging appears regardless of verbose flag since it's actionable information about resource decisions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation was straightforward. The mention_count was already being calculated in should_skip_entity(), so extracting it from payload.occurrences was consistent with existing patterns.

## Next Phase Readiness

- **Ready:** Image variety mechanism in place for entities with multiple mentions
- **Next:** Quality-based filtering (05-02) to filter out low-quality/ambiguous results from disambiguation
- **Future:** Timeline-aware image rotation (Phase 5 continuation) to use the additional images effectively

---
*Phase: 05-image-variety-quality*
*Completed: 2026-01-29*
