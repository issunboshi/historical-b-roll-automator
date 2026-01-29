# Phase 4: Disambiguation - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

When multiple Wikipedia articles match a search query, use LLM to select the contextually correct article based on transcript context. Includes confidence scoring to auto-accept high-confidence matches and flag uncertain ones for review. Disambiguation pages are detected and resolved by extracting linked articles.

</domain>

<decisions>
## Implementation Decisions

### Candidate Selection
- Fetch top 3 Wikipedia candidates per search query
- For each candidate, fetch summary (first paragraph) + categories list
- Disambiguation runs when 2+ candidates exist (any entity type)
- Single-result searches skip disambiguation entirely

### Confidence Scoring
- Score factors: context match quality + candidate clarity (how distinct alternatives are)
- Scale: 0-10 integer
- Confidence 7+: auto-accept, proceed with download
- Confidence 4-6: flag as "needs review" but still use the match
- Confidence 0-3: skip entity, mark as "no match" (no download)

### Review Workflow
- Dedicated review file (JSON) listing only flagged entities
- Review file includes: all candidates considered, chosen article, confidence score, LLM rationale, transcript context
- Manual override via JSON mapping file: `{"entity_name": "Wikipedia_Article_Title"}`
- Overrides file takes precedence when present

### Disambiguation Pages
- Detection method: Claude's discretion (categories, templates, or title patterns)
- Resolution: extract linked articles from disambiguation page, run disambiguation on those
- Extract top 5 article links from disambiguation pages
- Maximum disambiguation depth: 3 attempts (prevents infinite loops)

### Claude's Discretion
- Exact disambiguation page detection method (categories vs templates vs title patterns)
- Wikipedia API implementation details
- Caching strategy for disambiguation results
- Prompt engineering for confidence scoring

</decisions>

<specifics>
## Specific Ideas

- "Better to have no image than wrong image" — conservative approach for low-confidence matches
- Review file should make it easy to understand WHY disambiguation was uncertain
- Override mechanism allows power users to correct systematic errors

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-disambiguation*
*Context gathered: 2026-01-29*
