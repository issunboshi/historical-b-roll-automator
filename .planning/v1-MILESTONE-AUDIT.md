---
milestone: v1
audited: 2026-01-29T18:00:00Z
status: gaps_found
scores:
  requirements: 24/24
  phases: 5/5
  integration: 23/24
  flows: 3.5/4
gaps:
  requirements: []
  integration:
    - "--min-match-quality flag not exposed through broll.py CLI (Phase 5 integration)"
  flows:
    - "Quality filtering E2E flow incomplete - users cannot control quality threshold via pipeline command"
tech_debt: []
---

# v1 Milestone Audit Report

**Milestone:** v1 - Wikipedia Image Improvements
**Audited:** 2026-01-29T18:00:00Z
**Status:** GAPS FOUND
**Core Value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.

## Executive Summary

The v1 milestone is **95% complete**. All 24 requirements are implemented at the code level, all 5 phases passed verification, and 23 of 24 cross-phase connections are properly wired. However, one critical integration gap exists: the `--min-match-quality` CLI flag for Phase 5 quality filtering is not exposed through `broll.py`, requiring users to call `generate_broll_xml.py` directly to control quality thresholds.

## Requirements Coverage

| Category | Requirements | Complete | Partial | Unsatisfied |
|----------|-------------|----------|---------|-------------|
| Search Strategy | SRCH-01, SRCH-02, SRCH-03 | 3 | 0 | 0 |
| Disambiguation | DISAM-01 to DISAM-07 | 7 | 0 | 0 |
| Entity Prioritization | PRIO-01 to PRIO-05 | 5 | 0 | 0 |
| Image Variety | VAR-01, VAR-02, VAR-03 | 3 | 0 | 0 |
| Quality Tracking | QUAL-01 to QUAL-07 | 6 | 0 | 0 |
| **Total** | **24** | **24** | **0** | **0** |

All requirements satisfied at code level.

## Phase Verification Summary

| Phase | Name | Status | Score | Verified |
|-------|------|--------|-------|----------|
| 1 | Enrichment Foundation | PASSED | 5/5 | 2026-01-26 |
| 2 | Search Strategy Generation | PASSED | 4/4 | 2026-01-29 |
| 3 | Priority-Based Filtering | PASSED | 4/4 | 2026-01-29 |
| 4 | Disambiguation | PASSED | 9/9 | 2026-01-29 |
| 5 | Image Variety & Quality Filtering | PASSED | 5/5 | 2026-01-29 |

All phases passed verification with all success criteria met.

## Cross-Phase Integration

### Data Flow Verification

| From | To | Connection | Status |
|------|-----|------------|--------|
| Phase 1 (Enrichment) | Phase 2 (Strategies) | context field in enriched_entities.json | WIRED |
| Phase 1 (Enrichment) | Phase 3 (Filtering) | priority field used by should_skip_entity() | WIRED |
| Phase 2 (Strategies) | Phase 4 (Disambiguation) | search_strategies field feeds download | WIRED |
| Phase 4 (Disambiguation) | Phase 5 (Quality) | match_quality in disambiguation metadata | WIRED |
| Phase 5 (Quality) | broll.py CLI | --min-match-quality flag | **MISSING** |

### CLI Flag Passthrough

| Flag | Pipeline Parser | Download Args | XML Args | Status |
|------|----------------|---------------|----------|--------|
| --min-priority | ✓ | ✓ | N/A | WIRED |
| --batch-size | ✓ | N/A | N/A | WIRED |
| --cache-dir | ✓ | N/A | N/A | WIRED |
| --min-match-quality | **MISSING** | N/A | **MISSING** | **BROKEN** |
| --allow-non-pd | ✓ | N/A | ✓ | WIRED |
| --fps | ✓ | N/A | ✓ | WIRED |

## E2E User Flows

| Flow | Description | Status |
|------|-------------|--------|
| Full Pipeline | `broll.py pipeline --srt video.srt` produces timeline | COMPLETE |
| Priority Filtering | `--min-priority` reduces API calls | COMPLETE |
| Disambiguation | LLM picks contextually correct Wikipedia article | COMPLETE |
| Quality Filtering | Filter timeline by match_quality threshold | **PARTIAL** - CLI control missing |

### Flow 4 Detail: Quality Filtering (PARTIAL)

**What works:**
- Phase 4 writes `disambiguation.match_quality` to entity payloads
- Phase 5 reads and filters based on QUALITY_ORDER comparison
- `generate_broll_xml.py --min-match-quality medium` works directly

**What's broken:**
- `broll.py pipeline --min-match-quality medium` fails (flag not recognized)
- `broll.py xml --min-match-quality medium` fails (flag not recognized)

**User impact:** Must call `python generate_broll_xml.py` directly to control quality filtering.

## Critical Gap

### GAP-001: Quality Filtering CLI Integration

**Severity:** Critical
**Phase:** Phase 5
**Requirement:** QUAL-06

**Description:**
The `--min-match-quality` flag exists in `generate_broll_xml.py` (line 311) but is not exposed through `broll.py` orchestrator commands (`pipeline` and `xml`). This breaks the E2E user experience — users expect all features to be controllable through the main CLI.

**Root cause:**
Phase 5 planning documented the flag in `generate_broll_xml.py` but did not include a task to wire it through `broll.py`.

**Missing code locations:**
1. `broll.py` line ~654 (p_xml arguments): needs `p_xml.add_argument('--min-match-quality', ...)`
2. `broll.py` line ~578 (p_pipeline arguments): needs `p_pipeline.add_argument('--min-match-quality', ...)`
3. `broll.py` cmd_xml(): needs to extract and pass min_match_quality to subprocess
4. `broll.py` cmd_pipeline() xml_args: needs `min_match_quality=getattr(args, 'min_match_quality', 'high')`

**Estimated fix:** 4 lines of code, ~5 minutes

**Workaround:** Call `python generate_broll_xml.py --map output/strategies_entities.json --min-match-quality medium` directly instead of using `broll.py xml`.

## Tech Debt

None accumulated. All phases implemented cleanly without deferred items, placeholders, or TODOs.

## Module Quality

| Module | Lines | Stub Patterns | Anti-Patterns | Status |
|--------|-------|---------------|---------------|--------|
| tools/enrich_entities.py | 571 | None | None | Clean |
| tools/generate_search_strategies.py | 628 | None | None | Clean |
| tools/download_entities.py | 912 | None | None | Clean |
| tools/disambiguation.py | 1178 | None | None | Clean |
| generate_broll_xml.py | 518 | None | None | Clean |
| broll.py | 700+ | None | None | Clean |

## Integration Health Score

**23/24 connections working (95%)**

- Phase 1 → Phase 2 data flow ✓
- Phase 2 → Phase 4 data flow ✓
- Phase 1 → Phase 3 filtering ✓
- Phase 4 → Phase 5 data flow ✓
- Pipeline orchestration ✓
- Error handling ✓
- Module imports ✓
- Priority filtering CLI ✓
- Image rotation ✓
- **Quality filtering CLI ✗** (flag not exposed)

## Recommendation

**Do not complete milestone until GAP-001 is closed.**

The gap is small (4 lines of code) but represents incomplete integration of a key Phase 5 feature (QUAL-06). Users expect `broll.py pipeline --min-match-quality medium` to work.

**Next step:** `/gsd:plan-milestone-gaps` to create a closure plan.

---

*Audited: 2026-01-29T18:00:00Z*
*Auditor: Claude (gsd-audit-milestone)*
