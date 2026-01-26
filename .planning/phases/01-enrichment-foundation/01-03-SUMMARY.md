---
phase: 01-enrichment-foundation
plan: 03
subsystem: pipeline
tags: [cli, enrichment, pipeline, json, atomic-write]

# Dependency graph
requires:
  - phase: 01-01
    provides: priority scoring functions (calculate_priority, TYPE_WEIGHTS)
  - phase: 01-02
    provides: context extraction functions (extract_entity_context)
provides:
  - CLI interface for enrich_entities.py with --map, --srt, --out
  - enrich_entities() function orchestrating scoring + context
  - broll.py enrich command for standalone enrichment
  - Updated pipeline: extract -> enrich -> download -> xml
  - enriched_entities.json checkpoint file with priority and context per entity
affects: [02-query-generation, 03-adaptive-pipeline, 04-disambiguation]

# Tech tracking
tech-stack:
  added: []
  patterns: [atomic file write via temp + rename, dual import fallback for module/script contexts]

key-files:
  created: []
  modified:
    - tools/enrich_entities.py
    - broll.py

key-decisions:
  - "Enrichment writes separate file (enriched_entities.json) preserving original entities_map.json"
  - "Atomic write pattern: temp file + os.replace for safe JSON output"
  - "Dual import fallback (tools.srt_entities / srt_entities) for script and module contexts"

patterns-established:
  - "CLI pattern: argparse with required --map and --srt, optional --out defaulting to same dir"
  - "Pipeline integration: cmd_* functions receive Namespace args, call subprocess"

# Metrics
duration: 8min
completed: 2026-01-26
---

# Phase 1 Plan 3: Pipeline Wiring Summary

**CLI and pipeline integration for enrichment stage with atomic JSON output and checkpoint file generation**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-26T10:00:00Z
- **Completed:** 2026-01-26T10:08:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- enrich_entities.py now has full CLI interface accepting entities_map + SRT, outputting enriched JSON
- broll.py has new "enrich" subcommand matching extract/download/xml pattern
- Pipeline runs 4-step flow: extract -> enrich -> download -> xml
- Downstream steps (download, xml) consume enriched_entities.json with priority and context

## Task Commits

Each task was committed atomically:

1. **Task 1: Complete enrich_entities.py with main() and CLI** - `9b5e107` (feat)
2. **Task 2: Add enrich command to broll.py** - `86ab2ec` (feat)
3. **Task 3: Update pipeline command to include enrich step** - `4db2734` (feat)

**Deviation fix:** `5787950` (fix: import fallback for module/script contexts)

## Files Created/Modified

- `tools/enrich_entities.py` - Added enrich_entities() orchestration function, main() CLI entry point, atomic file write
- `broll.py` - Added cmd_enrich() handler, enrich subparser, updated pipeline to 4 steps, updated status scripts list

## Decisions Made

- **Separate output file**: enriched_entities.json preserves original entities_map.json for debugging and rollback
- **Atomic write pattern**: Uses tempfile + os.replace to prevent partial writes on failure
- **Entity-level error handling**: Individual enrichment failures mark entity as "failed" but don't abort entire run

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed import path for tools.srt_entities**

- **Found during:** Task 3 verification (end-to-end test)
- **Issue:** `from tools.srt_entities import parse_srt` fails when script run via subprocess because tools/ is not a package in sys.path
- **Fix:** Added try/except with fallback to `from srt_entities import parse_srt`
- **Files modified:** tools/enrich_entities.py
- **Verification:** `python broll.py enrich --map test_entities.json --srt transcript.srt` succeeds
- **Committed in:** 5787950

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Import fix necessary for subprocess execution. No scope creep.

## Issues Encountered

None beyond the import path issue noted in deviations.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Enrichment stage complete and wired into pipeline
- Each entity now has priority (0.0-1.2) and context (transcript text) fields
- Ready for Phase 2 (Query Generation) to use context for LLM-generated search queries
- Checkpoint file (enriched_entities.json) available for inspection/debugging

---
*Phase: 01-enrichment-foundation*
*Completed: 2026-01-26*
