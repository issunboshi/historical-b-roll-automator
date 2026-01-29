---
phase: 03-priority-based-filtering
plan: 02
subsystem: cli
tags: [argparse, cli, filtering, priority, subprocess]

# Dependency graph
requires:
  - phase: 03-01
    provides: Priority filtering in download_entities.py with --min-priority and -v flags
provides:
  - Priority filtering flags exposed through broll.py pipeline and download commands
  - User-facing CLI integration with proper passthrough to underlying scripts

affects: [user-documentation, phase-04-filtering]

# Tech tracking
tech-stack:
  added: []
  patterns: [CLI flag passthrough via argparse.Namespace, subprocess argument forwarding]

key-files:
  created: []
  modified: [broll.py]

key-decisions:
  - "CLI flags pass through from broll.py to download_entities.py subprocess"
  - "Both pipeline and download commands expose identical filtering flags"
  - "Verbose flag uses -v short form for consistency with Unix conventions"

patterns-established:
  - "Flag passthrough pattern: Check with hasattr/getattr, then extend subprocess cmd array"
  - "Pipeline command forwards args to download via argparse.Namespace"

# Metrics
duration: 3min
completed: 2026-01-29
---

# Phase 03 Plan 02: Expose Priority Filtering Through broll.py CLI Summary

**Priority filtering flags (--min-priority, -v/--verbose) exposed through broll.py pipeline and download commands with proper subprocess passthrough**

## Performance

- **Duration:** 3 min 14 sec
- **Started:** 2026-01-29T14:42:46Z
- **Completed:** 2026-01-29T14:46:02Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Users can now control priority filtering from broll.py without invoking download_entities.py directly
- Both pipeline and download commands support --min-priority and -v/--verbose flags
- Flags properly pass through from broll.py to download_entities.py subprocess
- Help text explains filtering behavior and defaults

## Task Commits

Each task was committed atomically:

1. **Task 1: Add filtering flags to broll.py CLI and passthrough** - `d7d4b15` (feat)

## Files Created/Modified
- `broll.py` - Added --min-priority and -v/--verbose flags to pipeline and download subparsers, updated cmd_download() to pass flags to subprocess, updated cmd_pipeline() download_args Namespace

## Decisions Made

None - followed plan as specified. Plan accurately identified all required changes:
- Exact line numbers for additions
- Proper use of getattr() for safe attribute access
- Correct subprocess cmd.extend() pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - straightforward CLI flag additions and passthrough implementation.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for user testing:**
- Users can now run `python broll.py pipeline --srt video.srt --min-priority 0.8 -v` to filter low-priority entities with verbose output
- Users can run `python broll.py download --map entities.json --min-priority 0` to disable filtering
- All filtering functionality from Phase 03-01 now accessible through the main CLI entry point

**Gap closure complete:**
- broll.py now exposes all download_entities.py filtering capabilities
- No need for users to understand internal script structure
- Consistent flag naming and behavior across all commands

---
*Phase: 03-priority-based-filtering*
*Completed: 2026-01-29*
