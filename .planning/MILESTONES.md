# Project Milestones: B-Roll Automater

## v2 Quality, Accuracy & Pipeline Expansion (Implemented: 2026-02-10)

**Delivered:** Era-aware disambiguation, frequency capping, entity deduplication, transcript summarization, REST API, visual element extraction, and montage detection.

**Key accomplishments:**

- Frequency capping to prevent pervasive entities from flooding timelines (configurable max-placements)
- Transcript summarization via LLM — auto-detects era, topic, pervasive entities, entity clusters
- Entity deduplication — merges transcription variants using LLM clusters + fuzzy matching
- Era-aware search strategies — contextual queries with chronological guidance for historical content
- Era-aware disambiguation — chronological fit checks reject wrong-century matches
- Era-aware image ordering — prioritizes historically appropriate images
- REST API (FastAPI) with file upload, async pipeline execution, disambiguation endpoints
- Docker deployment with health checks
- Visual element extraction (stats, quotes, processes, comparisons)
- DaVinci Resolve marker generation from visual elements
- Montage/collage opportunity detection

**Pipeline steps:** 11 (extract, extract-visuals, enrich, summarize, merge-entities, montages, strategies, disambiguate, download, markers, xml)

**Design docs:** See `docs/plans/archive/`

**Pending:** End-to-end validation on real data (1857 India SRT)

---

## v1 Wikipedia Image Improvements (Shipped: 2026-01-29)

**Delivered:** Intelligent, context-aware Wikipedia image matching that finds the RIGHT image for each entity without manual fixes.

**Phases completed:** 1-6 (14 plans total)

**Key accomplishments:**

- Enrichment infrastructure with priority scoring (type + mentions + position) and transcript context extraction
- LLM-generated search strategies using Claude to create contextual Wikipedia queries
- Priority-based filtering to skip low-value entities and reduce wasted API calls
- Context-aware disambiguation with confidence scoring (auto-accept/flag/skip routing)
- Image variety through round-robin rotation for multi-mention entities
- Quality-based timeline filtering with full CLI integration

**Stats:**

- 6 phases, 14 plans, ~42 tasks
- ~4,500 lines of Python added/modified
- 4 days from start to ship (2026-01-25 → 2026-01-29)
- 0.92 hours total execution time

**Git range:** `feat(01-01)` → `feat(06-01)`

**What's next:** v2 planning — context enhancement (temporal/geographic), advanced prioritization, caching

---
