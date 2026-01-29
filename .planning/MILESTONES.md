# Project Milestones: B-Roll Automater

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
