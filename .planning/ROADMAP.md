# Roadmap: B-Roll Automater - Wikipedia Image Improvements

## Overview

This roadmap transforms the existing Wikipedia image download pipeline from naive name-based search into an intelligent, context-aware system. Starting with enrichment infrastructure (Phase 1), adding LLM-generated search strategies (Phase 2), filtering low-value entities (Phase 3), implementing disambiguation logic (Phase 4), and finishing with quality tracking and image variety (Phase 5). Each phase builds on the previous, maintaining the pipeline's checkpoint-based architecture while adding intelligence where it matters most.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Enrichment Foundation** - Add enrichment infrastructure and priority scoring (completed 2026-01-26)
- [x] **Phase 2: Search Strategy Generation** - LLM-generated Wikipedia search queries (completed 2026-01-29)
- [x] **Phase 3: Priority-Based Filtering** - Skip low-value entities based on type and mentions (completed 2026-01-29)
- [x] **Phase 4: Disambiguation** - Context-aware Wikipedia disambiguation with confidence scoring (completed 2026-01-29)
- [x] **Phase 5: Image Variety & Quality Filtering** - Multi-image rotation and quality-based timeline filtering (completed 2026-01-29)

## Phase Details

### Phase 1: Enrichment Foundation
**Goal**: Pipeline can augment entity metadata with priority scores and transcript context before download attempts
**Depends on**: Nothing (first phase)
**Requirements**: PRIO-01, PRIO-02, PRIO-03
**Success Criteria** (what must be TRUE):
  1. New enrichment stage exists between extraction and download in pipeline
  2. Each entity has priority score (0.0-1.2) based on type, mention count, and position
  3. Each entity has transcript context (surrounding text from mentions)
  4. Pipeline command `broll.py pipeline` includes enrich step
  5. Enriched entities_map.json contains priority and context fields
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Priority scoring with TDD (type weights, mention multiplier, position boost) - completed 2026-01-26
- [x] 01-02-PLAN.md — Context extraction with TDD (sliding window, overlap deduplication) - completed 2026-01-26
- [x] 01-03-PLAN.md — Pipeline integration (CLI, broll.py enrich command, checkpoint output) - completed 2026-01-26

### Phase 2: Search Strategy Generation
**Goal**: Download stage uses LLM-generated search queries instead of naive entity names, improving Wikipedia match success rate
**Depends on**: Phase 1
**Requirements**: SRCH-01, SRCH-02, SRCH-03
**Success Criteria** (what must be TRUE):
  1. LLM generates 2-3 Wikipedia search queries per entity during enrichment
  2. Download stage iterates through search strategies in sequence until one succeeds
  3. Metadata records which search strategy succeeded for each entity
  4. LLM-suggested Wikipedia titles are validated (exist check) before download attempts
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — LLM search strategy generator (Pydantic schemas, Claude structured outputs, Wikipedia validation, caching) - completed 2026-01-29
- [x] 02-02-PLAN.md — Download stage strategy iteration (try all strategies, pick best, record metadata) - completed 2026-01-29
- [x] 02-03-PLAN.md — Pipeline integration (strategies subcommand, 5-step pipeline) - completed 2026-01-29

### Phase 3: Priority-Based Filtering
**Goal**: Pipeline skips downloading images for low-value entities based on priority scores and entity-type rules, reducing wasted Wikipedia API calls
**Depends on**: Phase 1 (uses priority scores from enrichment)
**Requirements**: PRIO-04, PRIO-05
**Success Criteria** (what must be TRUE):
  1. Entities below configurable priority threshold are skipped during download
  2. Places require minimum 2 mentions OR early mention (first 10%) to download
  3. Skipped entities are logged with reason for transparency
  4. CLI flag --min-priority controls filtering behavior (default 0.5, 0 disables)
**Plans**: 2 plans

Plans:
- [x] 03-01-PLAN.md — Add priority-based filtering to download stage with CLI flags, verbose logging, and skipped entity tracking - completed 2026-01-29
- [x] 03-02-PLAN.md — Expose filtering flags through broll.py pipeline and download commands (gap closure) - completed 2026-01-29

### Phase 4: Disambiguation
**Goal**: When multiple Wikipedia articles match a search, LLM picks the contextually correct one with confidence scoring
**Depends on**: Phase 2
**Requirements**: DISAM-01, DISAM-02, DISAM-03, DISAM-04, DISAM-05, DISAM-06, DISAM-07, QUAL-01, QUAL-02, QUAL-03, QUAL-04, QUAL-05, QUAL-07
**Success Criteria** (what must be TRUE):
  1. Wikipedia searches return top 3 candidates per query instead of just first result
  2. When 2+ candidates exist, LLM compares summaries against transcript context
  3. Disambiguation pages are detected via categories/templates and resolved (not used directly)
  4. Each disambiguation decision has confidence score (0-10)
  5. Results with confidence >=7 are auto-accepted
  6. Results with confidence 4-6 are flagged as "needs review" in metadata
  7. Disambiguation depth limited to 3 attempts (prevents infinite loops)
  8. Match quality (high/medium/low/none) recorded for each entity
  9. Disambiguation log includes candidates considered, chosen article, confidence, and rationale
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Disambiguation module (multi-candidate search, disambiguation page detection, LLM decisions with confidence scoring) - completed 2026-01-29
- [x] 04-02-PLAN.md — Quality tracking and review files (confidence routing, match quality, review/override JSON) - completed 2026-01-29
- [x] 04-03-PLAN.md — Download stage integration (wire disambiguation into download flow) - completed 2026-01-29

### Phase 5: Image Variety & Quality Filtering
**Goal**: Entities mentioned multiple times use different images at each mention, and timeline generation filters by match quality
**Depends on**: Phase 4
**Requirements**: VAR-01, VAR-02, VAR-03, QUAL-06
**Success Criteria** (what must be TRUE):
  1. When entity mentioned multiple times and has multiple good images, different images used at different mentions
  2. Metadata tracks which image used for which occurrence
  3. Download stage fetches up to 5 images (instead of 3) for multi-mention entities
  4. Timeline generation has --min-match-quality flag to filter entities by match quality
  5. Entities below minimum match quality threshold excluded from timeline
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — Dynamic image count for multi-mention entities (5 images for 3+ mentions) - completed 2026-01-29
- [x] 05-02-PLAN.md — Image rotation metadata tracking and quality-based timeline filtering - completed 2026-01-29

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Enrichment Foundation | 3/3 | Complete | 2026-01-26 |
| 2. Search Strategy Generation | 3/3 | Complete | 2026-01-29 |
| 3. Priority-Based Filtering | 2/2 | Complete | 2026-01-29 |
| 4. Disambiguation | 3/3 | Complete | 2026-01-29 |
| 5. Image Variety & Quality Filtering | 2/2 | Complete | 2026-01-29 |
