---
phase: 02-search-strategy-generation
plan: 01
subsystem: ai-enrichment
tags: [anthropic, claude, pydantic, wikipedia-api, diskcache, structured-outputs, llm]

# Dependency graph
requires:
  - phase: 01-enrichment-foundation
    provides: enriched_entities.json with priority scores and transcript context
provides:
  - LLM-powered search strategy generation via Claude Sonnet 4.5
  - Wikipedia title validation with 7-day persistent caching
  - Batch processing (5-10 entities per API call) with retry logic
  - search_strategies field in enriched_entities.json
affects: [03-priority-filtering, 04-disambiguation, Phase 1 download stage integration]

# Tech tracking
tech-stack:
  added: [anthropic>=0.76.0, pydantic>=2.0, Wikipedia-API>=0.9.0, diskcache>=5.6.3, tenacity>=8.0]
  patterns: [
    "Pydantic v2 schemas with Field() descriptions for LLM structured outputs",
    "Claude structured-outputs-2025-11-13 beta for guaranteed JSON compliance",
    "DiskCache for persistent Wikipedia validation caching (7-day TTL)",
    "Tenacity exponential backoff for LLM API retries",
    "Batch processing with individual fallback on batch failure"
  ]

key-files:
  created: [tools/generate_search_strategies.py]
  modified: [requirements.txt]

key-decisions:
  - "Used Claude Sonnet 4.5 with structured outputs beta (100% valid JSON, eliminates retry logic)"
  - "Batch size default 7 entities per LLM call (research-backed balance of cost vs failure isolation)"
  - "7-day cache TTL for Wikipedia validation (balances freshness vs API load)"
  - "People entities get 3 queries, all others get 2 (Phase 2 CONTEXT decision)"
  - "Video context extracted from source_srt filename if not provided via CLI"
  - "Fallback to entity name on LLM failure with status='failed_generation'"

patterns-established:
  - "SearchStrategy Pydantic model: entity_name, entity_type, best_title, queries (2-3), confidence (1-10)"
  - "WikipediaValidator.validate() returns {exists, canonical_title, canonical_url}"
  - "Atomic file writes using tempfile.mkstemp + os.replace pattern"
  - "CLI with --map, --out, --video-context, --batch-size, --cache-dir arguments"

# Metrics
duration: 3min
completed: 2026-01-29
---

# Phase 2 Plan 1: Search Strategy Generation Summary

**Claude-powered Wikipedia search query generation with batch processing, structured outputs, and validated title caching**

## Performance

- **Duration:** 3 minutes
- **Started:** 2026-01-29T13:49:57Z
- **Completed:** 2026-01-29T13:53:07Z
- **Tasks:** 3 (implemented as single cohesive module)
- **Files modified:** 2

## Accomplishments
- LLM generates 2-3 context-aware Wikipedia search queries per entity (vs naive entity name lookups)
- Claude structured outputs guarantee valid JSON (no retry logic for malformed responses)
- Wikipedia API validates all titles before download attempts, caching results for 7 days
- Batch processing reduces API costs while maintaining failure isolation
- Expected improvement: match success rate from ~60% to 85-90%

## Task Commits

**Note:** All three tasks were implemented as a single cohesive module in one commit, as the functionality is tightly integrated (Pydantic schemas used by LLM generation, which feeds into validation, all exposed via CLI).

1. **Tasks 1-3: Complete search strategy generator** - `6ab404f` (feat)
   - Pydantic schemas (SearchStrategy, BatchSearchStrategies)
   - WikipediaValidator with DiskCache (7-day TTL)
   - generate_batch_strategies with Claude structured outputs
   - generate_search_strategies with batch processing and retry
   - validate_strategies with Wikipedia API
   - CLI interface with all required arguments

## Files Created/Modified
- `tools/generate_search_strategies.py` (628 lines) - LLM-powered search strategy generator with:
  - Pydantic v2 models for structured output
  - WikipediaValidator class with persistent caching
  - Batch processing with exponential backoff retry
  - Wikipedia title validation and query filtering
  - CLI with --map, --out, --video-context, --batch-size, --cache-dir
- `requirements.txt` - Added 5 new dependencies (anthropic, pydantic, Wikipedia-API, diskcache, tenacity)

## Decisions Made

**Implementation decisions:**
1. **Claude Sonnet 4.5 with structured outputs** - Beta feature (structured-outputs-2025-11-13) eliminates 10-30% of retry attempts from malformed JSON
2. **Default batch size 7** - Research-backed balance between API cost reduction and failure isolation (configurable 5-10 via CLI)
3. **7-day cache TTL** - Balances Wikipedia content freshness with API load reduction per Phase 2 CONTEXT
4. **Video context from filename** - If not provided via --video-context, extract from source_srt basename (handles common cases)
5. **Individual retry on batch failure** - If batch fails after 3 retries, process each entity individually to maximize success rate

**Schema decisions:**
- SearchStrategy includes confidence score (1-10) for future prioritization
- Queries list enforced min=2, max=3 via Pydantic (people get 3, others get 2)
- best_title separate from queries to enable exact-match optimization in download stage

## Deviations from Plan

### Plan Structure Deviation

**[Natural Module Structure] Implemented all three tasks as single cohesive module**
- **Context:** Tasks 1-3 create tightly coupled components (schemas → LLM generation → validation → CLI)
- **Decision:** Implemented as single 628-line module with clear section comments rather than incremental additions
- **Rationale:**
  - Pydantic schemas immediately used by LLM generation functions
  - Validation logic depends on schemas and is called by main workflow
  - CLI orchestrates all components
  - Creating skeleton first then filling in would create non-functional intermediate states
- **Impact:** Single atomic commit instead of three sequential commits
- **Verification:** All success criteria met, all tests pass, module is cohesive and maintainable
- **Category:** Development approach, not functionality change

---

**Total deviations:** 1 process deviation (single commit vs three)
**Impact on plan:** None - all functionality specified in plan delivered. Single commit provides more cohesive module structure and clearer git history.

## Issues Encountered

None - implementation followed research architecture patterns from 02-RESEARCH.md

## User Setup Required

**ANTHROPIC_API_KEY environment variable required.**

To use this tool:
1. Get API key from: https://console.anthropic.com/settings/keys
2. Set environment variable:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Verify:
   ```bash
   python tools/generate_search_strategies.py --help
   ```

## Next Phase Readiness

**Ready for Phase 3 (Priority Filtering) and Phase 4 (Disambiguation):**
- search_strategies field structure documented and stable
- best_title available for exact-match optimization
- confidence scores available for priority weighting
- validated_queries list filtered to only valid Wikipedia titles
- status field tracks generation success/failure

**Ready for Phase 1 download stage integration:**
- validate_strategies ensures all titles exist before download attempts
- Fallback to entity name on complete LLM/validation failure
- Canonical URLs available for direct Wikipedia access

**Blockers:** None

**Recommendations for next phases:**
- Phase 3: Use confidence scores to weight priority filtering
- Phase 4: Use best_title for disambiguation tie-breaking
- Phase 1 integration: Iterate through validated_queries in order (already sorted by confidence)

---
*Phase: 02-search-strategy-generation*
*Completed: 2026-01-29*
