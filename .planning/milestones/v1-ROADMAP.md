# Milestone v1: Wikipedia Image Improvements

**Status:** SHIPPED 2026-01-29
**Phases:** 1-6
**Total Plans:** 14

## Overview

This roadmap transformed the existing Wikipedia image download pipeline from naive name-based search into an intelligent, context-aware system. Starting with enrichment infrastructure (Phase 1), adding LLM-generated search strategies (Phase 2), filtering low-value entities (Phase 3), implementing disambiguation logic (Phase 4), and finishing with quality tracking and image variety (Phase 5-6). Each phase built on the previous, maintaining the pipeline's checkpoint-based architecture while adding intelligence where it matters most.

## Phases

### Phase 1: Enrichment Foundation

**Goal**: Pipeline can augment entity metadata with priority scores and transcript context before download attempts
**Depends on**: Nothing (first phase)
**Requirements**: PRIO-01, PRIO-02, PRIO-03
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Priority scoring with TDD (type weights, mention multiplier, position boost)
- [x] 01-02-PLAN.md — Context extraction with TDD (sliding window, overlap deduplication)
- [x] 01-03-PLAN.md — Pipeline integration (CLI, broll.py enrich command, checkpoint output)

**Completed:** 2026-01-26

### Phase 2: Search Strategy Generation

**Goal**: Download stage uses LLM-generated search queries instead of naive entity names, improving Wikipedia match success rate
**Depends on**: Phase 1
**Requirements**: SRCH-01, SRCH-02, SRCH-03
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — LLM search strategy generator (Pydantic schemas, Claude structured outputs, Wikipedia validation, caching)
- [x] 02-02-PLAN.md — Download stage strategy iteration (try all strategies, pick best, record metadata)
- [x] 02-03-PLAN.md — Pipeline integration (strategies subcommand, 5-step pipeline)

**Completed:** 2026-01-29

### Phase 3: Priority-Based Filtering

**Goal**: Pipeline skips downloading images for low-value entities based on priority scores and entity-type rules, reducing wasted Wikipedia API calls
**Depends on**: Phase 1 (uses priority scores from enrichment)
**Requirements**: PRIO-04, PRIO-05
**Plans**: 2 plans

Plans:
- [x] 03-01-PLAN.md — Add priority-based filtering to download stage with CLI flags, verbose logging, and skipped entity tracking
- [x] 03-02-PLAN.md — Expose filtering flags through broll.py pipeline and download commands (gap closure)

**Completed:** 2026-01-29

### Phase 4: Disambiguation

**Goal**: When multiple Wikipedia articles match a search, LLM picks the contextually correct one with confidence scoring
**Depends on**: Phase 2
**Requirements**: DISAM-01 through DISAM-07, QUAL-01 through QUAL-05, QUAL-07
**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Disambiguation module (multi-candidate search, disambiguation page detection, LLM decisions with confidence scoring)
- [x] 04-02-PLAN.md — Quality tracking and review files (confidence routing, match quality, review/override JSON)
- [x] 04-03-PLAN.md — Download stage integration (wire disambiguation into download flow)

**Completed:** 2026-01-29

### Phase 5: Image Variety & Quality Filtering

**Goal**: Entities mentioned multiple times use different images at each mention, and timeline generation filters by match quality
**Depends on**: Phase 4
**Requirements**: VAR-01, VAR-02, VAR-03, QUAL-06
**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — Dynamic image count for multi-mention entities (5 images for 3+ mentions)
- [x] 05-02-PLAN.md — Image rotation metadata tracking and quality-based timeline filtering

**Completed:** 2026-01-29

### Phase 6: Quality Filtering CLI Integration

**Goal**: Expose --min-match-quality flag through broll.py so users can control quality thresholds via the main CLI
**Depends on**: Phase 5
**Requirements**: QUAL-06 (CLI integration)
**Gap Closure**: Closes GAP-001 from v1 audit
**Plans**: 1 plan

Plans:
- [x] 06-01-PLAN.md — Wire --min-match-quality through broll.py pipeline and xml commands

**Completed:** 2026-01-29

---

## Milestone Summary

**Key Decisions:**

- Use LLM for search strategy generation (Claude has story context, can suggest contextual queries)
- Use LLM for disambiguation (compare Wikipedia summaries against transcript context)
- Prioritize people/events over places (visually distinctive vs. contextually repetitive)
- Claude structured outputs eliminate 10-30% retry attempts from malformed JSON
- Default batch size 7 entities per LLM call (research-backed balance)
- 7-day cache TTL for Wikipedia validation (balances freshness vs API load)
- Stop at first successful search term (efficiency over exhaustiveness)
- Confidence routing: 7+ auto-accept, 4-6 flag for review, 0-3 skip entirely
- Default quality threshold: high (only high-quality matches in timeline)

**Issues Resolved:**

- Ambiguous entity names now resolved via context-aware disambiguation
- Naive Wikipedia searches replaced with LLM-generated contextual queries
- Low-value entities filtered out before expensive API calls
- Single images for multi-mention entities replaced with round-robin rotation

**Issues Deferred:**

- Temporal context extraction (v2)
- Geographic context extraction (v2)
- Alias variation fallbacks (v2)
- Entity-type-specific disambiguation strategies (v2)
- Disambiguation result caching (v2)

**Technical Debt Incurred:**

None identified.

---

_For current project status, see .planning/ROADMAP.md (created for next milestone)_
