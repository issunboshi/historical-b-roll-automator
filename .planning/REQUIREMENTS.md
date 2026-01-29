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
- [x] **DISAM-06**: Auto-accept disambiguation results with confidence ≥7
- [x] **DISAM-07**: Flag results with confidence 4-6 as "needs review" in metadata

### Entity Prioritization

- [x] **PRIO-01**: Calculate priority score for each entity based on type (people=1.0, events=0.9, concepts=0.6, places=0.3)
- [x] **PRIO-02**: Boost priority for entities mentioned multiple times (diminishing returns: 1.3x at 2, 1.5x at 3, 1.6x at 4+)
- [x] **PRIO-03**: Boost priority for entities mentioned in first 20% of transcript (1.1x multiplier)
- [x] **PRIO-04**: Skip image download for entities below configurable priority threshold (default 0.3)
- [x] **PRIO-05**: For places, require minimum 2 mentions OR early mention (first 10%) to download

### Image Variety

- [ ] **VAR-01**: When entity has multiple good images and is mentioned multiple times, use different images at different mentions
- [ ] **VAR-02**: Track which images used for which occurrences in metadata
- [ ] **VAR-03**: Download extra images (up to 5 instead of 3) when entity has multiple mentions

### Quality Tracking

- [x] **QUAL-01**: Record match quality (high/medium/low/none) for each entity based on search and disambiguation results
- [x] **QUAL-02**: High quality = single result or confident disambiguation (≥7)
- [x] **QUAL-03**: Medium quality = successful disambiguation with moderate confidence (4-6) or fallback strategy
- [x] **QUAL-04**: Low quality = all strategies failed but got some result
- [x] **QUAL-05**: None = no Wikipedia results found
- [ ] **QUAL-06**: Timeline generation filters entities by minimum match quality (configurable, default: medium)
- [x] **QUAL-07**: Log all disambiguation decisions with candidates considered, chosen article, confidence, and rationale

## v2 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Context Enhancement

- **CTX-01**: Extract temporal context (year, decade, era) from transcript for query enhancement
- **CTX-02**: Extract geographic context (location keywords, nearby place entities) for query enhancement
- **CTX-03**: Use alias variations from entity extraction as fallback search strategies

### Advanced Prioritization

- **PRIO-06**: Entity-type-specific disambiguation strategies (people prefer biographies, places prefer main articles)
- **PRIO-07**: Priority-based track assignment in timeline (high-priority entities on more visible tracks)

### Caching

- **CACHE-01**: Cache disambiguation results across runs (entity + context → Wikipedia article)
- **CACHE-02**: Cache expiration after 30 days

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Image quality analysis (resolution, composition) | Images shown small as PiP; fine details don't matter |
| Manual image curation UI | CLI tool, not GUI application |
| Non-Wikipedia image sources | Wikipedia provides licensing metadata; other sources complicate rights |
| Wikidata integration | Adds complexity; defer unless Wikipedia-only approach shows <70% success |
| Real-time processing | Batch processing sufficient for workflow |
| Paid Wikipedia API access | No paid image search tiers exist; Wikimedia Enterprise is for dataset mirroring |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

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
| VAR-01 | Phase 5 | Pending |
| VAR-02 | Phase 5 | Pending |
| VAR-03 | Phase 5 | Pending |
| QUAL-01 | Phase 4 | Complete |
| QUAL-02 | Phase 4 | Complete |
| QUAL-03 | Phase 4 | Complete |
| QUAL-04 | Phase 4 | Complete |
| QUAL-05 | Phase 4 | Complete |
| QUAL-06 | Phase 5 | Pending |
| QUAL-07 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 24 total
- Mapped to phases: 24
- Unmapped: 0 ✓

---
*Requirements defined: 2026-01-25*
*Last updated: 2026-01-29 after Phase 4 completion*
