# Requirements Archive: v1 Wikipedia Image Improvements

**Archived:** 2026-01-29
**Status:** SHIPPED

This is the archived requirements specification for v1.
For current requirements, see `.planning/REQUIREMENTS.md` (created for next milestone).

---

# Requirements: B-Roll Automater - Wikipedia Image Improvements

**Defined:** 2026-01-25
**Core Value:** Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Search Strategy

- [x] **SRCH-01**: LLM generates 2-3 Wikipedia search queries per entity based on name + transcript context
- [x] **SRCH-02**: Download stage iterates through search strategies in sequence until one returns results
- [x] **SRCH-03**: Record which search strategy succeeded for each entity in metadata

### Disambiguation

- [x] **DISAM-01**: When Wikipedia search returns multiple results, fetch summaries for top 3 candidates
- [x] **DISAM-02**: LLM compares candidate summaries against transcript context and picks best match
- [x] **DISAM-03**: Detect disambiguation pages via categories/templates before attempting download
- [x] **DISAM-04**: Set maximum disambiguation depth (3 attempts) to prevent infinite loops
- [x] **DISAM-05**: Assign confidence score (0-10) to each disambiguation decision
- [x] **DISAM-06**: Auto-accept disambiguation results with confidence >=7
- [x] **DISAM-07**: Flag results with confidence 4-6 as "needs review" in metadata

### Entity Prioritization

- [x] **PRIO-01**: Calculate priority score for each entity based on type (people=1.0, events=0.9, concepts=0.6, places=0.3)
- [x] **PRIO-02**: Boost priority for entities mentioned multiple times (diminishing returns: 1.3x at 2, 1.5x at 3, 1.6x at 4+)
- [x] **PRIO-03**: Boost priority for entities mentioned in first 20% of transcript (1.1x multiplier)
- [x] **PRIO-04**: Skip image download for entities below configurable priority threshold (default 0.3)
- [x] **PRIO-05**: For places, require minimum 2 mentions OR early mention (first 10%) to download

### Image Variety

- [x] **VAR-01**: When entity has multiple good images and is mentioned multiple times, use different images at different mentions
- [x] **VAR-02**: Track which images used for which occurrences in metadata
- [x] **VAR-03**: Download extra images (up to 5 instead of 3) when entity has multiple mentions

### Quality Tracking

- [x] **QUAL-01**: Record match quality (high/medium/low/none) for each entity based on search and disambiguation results
- [x] **QUAL-02**: High quality = single result or confident disambiguation (>=7)
- [x] **QUAL-03**: Medium quality = successful disambiguation with moderate confidence (4-6) or fallback strategy
- [x] **QUAL-04**: Low quality = all strategies failed but got some result
- [x] **QUAL-05**: None = no Wikipedia results found
- [x] **QUAL-06**: Timeline generation filters entities by minimum match quality (configurable, default: medium)
- [x] **QUAL-07**: Log all disambiguation decisions with candidates considered, chosen article, confidence, and rationale

## Traceability

Which phases covered which requirements.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SRCH-01 | Phase 2 | Complete |
| SRCH-02 | Phase 2 | Complete |
| SRCH-03 | Phase 2 | Complete |
| DISAM-01 | Phase 4 | Complete |
| DISAM-02 | Phase 4 | Complete |
| DISAM-03 | Phase 4 | Complete |
| DISAM-04 | Phase 4 | Complete |
| DISAM-05 | Phase 4 | Complete |
| DISAM-06 | Phase 4 | Complete |
| DISAM-07 | Phase 4 | Complete |
| PRIO-01 | Phase 1 | Complete |
| PRIO-02 | Phase 1 | Complete |
| PRIO-03 | Phase 1 | Complete |
| PRIO-04 | Phase 3 | Complete |
| PRIO-05 | Phase 3 | Complete |
| VAR-01 | Phase 5 | Complete |
| VAR-02 | Phase 5 | Complete |
| VAR-03 | Phase 5 | Complete |
| QUAL-01 | Phase 4 | Complete |
| QUAL-02 | Phase 4 | Complete |
| QUAL-03 | Phase 4 | Complete |
| QUAL-04 | Phase 4 | Complete |
| QUAL-05 | Phase 4 | Complete |
| QUAL-06 | Phase 5, Phase 6 | Complete |
| QUAL-07 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 24 total
- Shipped: 24
- Dropped: 0

---

## Milestone Summary

**Shipped:** 24 of 24 v1 requirements
**Adjusted:** None
**Dropped:** None

---
*Archived: 2026-01-29 as part of v1 milestone completion*
