# Phase 2: Search Strategy Generation - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

LLM generates Wikipedia search queries instead of naive entity names, improving match success rate. The download stage uses these generated strategies to find the correct Wikipedia articles. This phase does NOT include disambiguation logic (Phase 4) or priority-based filtering (Phase 3).

</domain>

<decisions>
## Implementation Decisions

### Search Query Design
- Variable query count by entity type: People get 3 queries, other types get 2
- LLM decides when to include disambiguation hints (profession, era, location) based on entity name ambiguity
- LLM orders queries by confidence — most likely to succeed first

### LLM Prompt Structure
- Context provided to LLM: entity name, type, transcript context (from Phase 1), AND video topic/title
- LLM suggests best_title (likely exact Wikipedia article title) in addition to search queries
- Output format: Structured JSON (`{'best_title': '...', 'queries': ['...', '...'], 'confidence': 8}`)
- Batch processing: 5-10 entities per LLM call to reduce API calls

### Strategy Iteration Behavior
- Try ALL generated strategies, then pick best result (not stop on first success)
- Best match determined by: prefer exact title match to LLM's best_title guess, otherwise first successful result
- Fallback: if all LLM strategies fail, try original entity name but mark result as 'fallback match' in metadata

### Validation Approach
- Use Wikipedia API search to validate titles exist and get canonical form
- Persistent cache for Wikipedia validation results (7-day expiry)

### Claude's Discretion
- Level of metadata detail to record about successful strategy
- Behavior when best_title guess fails (log warning vs silent proceed)
- Exact batch size within 5-10 range based on entity complexity

</decisions>

<specifics>
## Specific Ideas

- Query count example for people: full name, common variation, and role-based (e.g., 'Elon Musk', 'Musk', 'Elon Musk entrepreneur')
- Video topic provides broader context — helps LLM understand if "Jordan" is Michael Jordan (basketball video) or Jordan country (travel video)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-search-strategy-generation*
*Context gathered: 2026-01-26*
