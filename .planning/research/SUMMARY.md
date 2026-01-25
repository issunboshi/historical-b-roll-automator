# Project Research Summary

**Project:** B-Roll Automater — Wikipedia Image Download Improvements
**Domain:** LLM-assisted Wikipedia search and disambiguation for entity image retrieval
**Researched:** 2026-01-25
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project enhances an existing B-roll automation pipeline that downloads Wikipedia images for entities extracted from video transcripts. The current implementation suffers from naive search strategies—it uses entity names directly, takes the first result without disambiguation, and has no context awareness. Research confirms that the bottleneck is search strategy and disambiguation logic, NOT Wikipedia API limits.

**Recommended approach:** Evolve the existing three-stage pipeline (extract → download → timeline) into a four-stage pipeline by adding an enrichment stage. This enrichment stage uses LLM to generate multiple search queries per entity and gather transcript context BEFORE download attempts. The download stage then iterates through these strategies and conditionally calls LLM for disambiguation only when multiple Wikipedia results exist. This approach maintains the pipeline's checkpoint-based architecture while adding intelligence where it matters most.

**Key risks:** (1) LLM hallucinating non-existent Wikipedia article titles causing silent failures, (2) disambiguation page infinite loops wasting API quota and LLM calls, and (3) parallel download execution without shared rate limiting triggering Wikipedia IP bans. All three risks are mitigable with proper validation, disambiguation detection, and rate limiting strategies identified in research.

## Key Findings

### Recommended Stack

The Wikipedia API stack requires no changes—the current MediaWiki Action API implementation is optimal. Wikipedia has NO paid tiers for higher throughput; the free API handles ~600 requests/minute which is well within project needs. Performance gains come from smarter queries, not API upgrades.

**Core technologies:**
- **MediaWiki Action API** (current v1) — Image search, metadata retrieval, page content. Already implemented with proper User-Agent, maxlag, and retry logic.
- **Wikipedia REST API** (v1, supplemental) — Page summaries for disambiguation. Lower overhead than full HTML parsing for disambiguation use cases.
- **OpenAI API / Ollama** — LLM for search query generation and disambiguation. Already integrated in extraction stage; reuse for enrichment and disambiguation.
- **requests** (2.31+) — Direct HTTP client. Current implementation is correct; no need for pywikibot or wikipedia library wrappers.

**Critical API considerations:**
- Rate limits: NONE for compliant bots with proper User-Agent (already implemented)
- Batch queries: Support up to 50 titles per imageinfo call (already implemented)
- Redirects: Must use `redirects=1` parameter (already implemented correctly)

### Expected Features

**Must have (table stakes):**
- **Multi-query search strategy generation** — LLM generates 2-4 Wikipedia search queries from entity name + transcript context. Foundation for all disambiguation.
- **Candidate result comparison** — When multiple Wikipedia pages match, LLM picks contextually correct one using transcript context.
- **Disambiguation page detection** — Detect and handle Wikipedia disambiguation pages that must be resolved (not usable articles).
- **Result validation** — Verify Wikipedia page exists and has images before accepting.
- **Search fallback chain** — Try progressively simpler queries if first attempts fail.

**Should have (competitive):**
- **Confidence scoring** — LLM rates each candidate 0-10; require ≥7 for auto-selection. Gates quality, reduces false positives.
- **Result explanation** — Log which query succeeded, candidates considered, selection rationale. Critical for debugging and validation.
- **Context-aware query expansion** — Generate domain-specific search terms using story context (time period, location, event type).
- **Alias-aware search** — Use canonical name + known aliases from entity extraction to try multiple searches.

**Defer (v2+):**
- **Temporal/geographic disambiguation** — Specialized improvements; context comparison handles this implicitly in MVP.
- **Wikidata integration** — For cross-language disambiguation; Wikipedia API + LLM sufficient for English-only use case.
- **Category-based filtering** — Advanced Wikipedia category analysis for disambiguation; defer until base approach validated.

### Architecture Approach

The existing three-stage pipeline (extract → download → timeline) evolves into a four-stage pipeline with an intermediate enrichment stage. LLM operations should augment entity metadata early, NOT block download operations. This maintains the pipeline's fail-fast semantics and resume-from-checkpoint design while adding intelligence.

**Major components:**
1. **Stage 1: Extract** (existing, `tools/srt_entities.py`) — LLM extracts entities from SRT transcript, outputs `entities_map.json` with canonical names and aliases.
2. **Stage 1.5: Enrich** (NEW, `tools/enrich_entities.py`) — Calculate priority scores, gather transcript context, LLM generates search strategies. Augments entities_map.json with `priority`, `context`, and `search_strategies` fields.
3. **Stage 2: Download** (enhanced, `tools/download_entities.py`) — Consume enriched metadata, iterate through search strategies, conditionally disambiguate with LLM, download images. Adds `search_used`, `disambiguation`, and `match_quality` tracking.
4. **Stage 3: Timeline** (enhanced, `generate_broll_xml.py`) — Use priority and match quality for intelligent image rotation and quality filtering.

**Key architectural patterns:**
- **Enrichment as separate stage** — Augment data in dedicated stage before consumption. Testable, cacheable, resume-friendly.
- **Multi-strategy search with fallback** — Try multiple search queries in sequence until one succeeds. Logged for debugging.
- **Conditional disambiguation** — Only call LLM when multiple Wikipedia results exist (typical: 10-30% of entities). Cost-efficient.
- **Priority-based processing** — Calculate entity priority early; skip low-value entities (e.g., places mentioned once late in transcript).

### Critical Pitfalls

1. **Rate limit ignorance → IP ban** — Current parallel implementation lacks shared rate limiter. Wikipedia escalates from soft throttling to hard IP ban. Fix: Implement shared rate limiter across workers BEFORE enabling parallelization. Current code has good retry logic but `-j` parallel flag doesn't share rate control.

2. **LLM hallucinating non-existent Wikipedia titles** — LLM generates plausible but non-existent article names. Code tries to fetch, gets no results, silent failure. Fix: Always verify LLM-suggested titles exist using `action=query&titles=` before download. Log hallucinations for debugging.

3. **Disambiguation page infinite loop** — LLM picks disambiguation page → Wikipedia returns another disambiguation page → loop continues. Fix: Detect disambiguation pages via categories/templates, set max depth limit (3 attempts), cache disambiguation results.

4. **LLM disambiguation bias → wrong person every time** — LLM picks famous person regardless of context (e.g., always American Revolution William Dawes despite Australian context). Fix: Context-heavy prompts emphasizing context matching over fame, require explicit reasoning output.

5. **Cost explosion from redundant LLM calls** — Calling LLM for every mention instead of unique entity. Fix: Current code already deduplicates via entities_map.json structure. Add persistent disambiguation cache across runs.

## Implications for Roadmap

Based on research, suggested phase structure follows incremental build order to maintain working pipeline at each step:

### Phase 1: Enrichment Foundation
**Rationale:** Add enrichment infrastructure without changing download behavior. Low-risk foundation for all subsequent improvements.

**Delivers:**
- New `tools/enrich_entities.py` skeleton
- Priority scoring (deterministic, no LLM)
- Context gathering from transcript
- Updated `broll.py pipeline` command to include enrich step

**Addresses:**
- Architecture foundation for multi-query search
- Priority-based filtering preparation

**Avoids:**
- No new LLM calls yet (low risk)
- No behavior changes (backward compatible)

**Research flag:** Skip `/gsd:research-phase` — straightforward file I/O and data structure augmentation.

### Phase 2: Search Strategy Generation
**Rationale:** Enable better Wikipedia searches through LLM-generated queries. Builds on enrichment foundation. Immediate value: entities that previously failed should now succeed.

**Delivers:**
- LLM call in `enrich_entities.py` for multi-query generation
- Enhanced `download_entities.py` to iterate through search_strategies
- `search_used` tracking in entity metadata

**Addresses:**
- Multi-query search strategy generation (table stakes)
- Search fallback chain (table stakes)

**Avoids:**
- LLM hallucination pitfall via title validation
- Cost explosion pitfall via deduplication (already in entities_map.json)

**Research flag:** Consider `/gsd:research-phase` for LLM prompt engineering patterns and token optimization strategies.

### Phase 3: Priority-Based Filtering
**Rationale:** Stop wasting time downloading images for low-value entities. Quick win with clear business value (fewer wasted downloads).

**Delivers:**
- Priority filtering logic in `download_entities.py`
- `--min-priority` and `--skip-places-threshold` CLI flags
- Skipped entity logging for transparency

**Addresses:**
- Priority-based processing pattern from architecture research
- Reduce noise from repetitive place images

**Avoids:**
- No pitfalls introduced; pure optimization

**Research flag:** Skip `/gsd:research-phase` — business logic based on entity type rules.

### Phase 4: Disambiguation
**Rationale:** Core intelligence upgrade. When multiple Wikipedia articles match, pick the right one. Most complex phase but highest value.

**Delivers:**
- Multi-result Wikipedia search (top 3 per strategy)
- LLM disambiguation call when 2+ results exist
- Disambiguation page detection and loop prevention
- `disambiguation` metadata tracking
- `--max-disambiguation-candidates` flag

**Addresses:**
- Candidate result comparison (table stakes)
- Disambiguation page detection (table stakes)
- Confidence scoring (differentiator)

**Avoids:**
- Disambiguation loop pitfall via detection and max depth
- Fame bias pitfall via context-heavy prompts
- Cost explosion pitfall via conditional LLM calls

**Research flag:** REQUIRES `/gsd:research-phase` — complex LLM prompt engineering for disambiguation, Wikipedia API disambiguation detection patterns, caching strategies.

### Phase 5: Match Quality & Variety
**Rationale:** Polish phase. Track confidence, use it for filtering, improve timeline generation.

**Delivers:**
- `match_quality` scoring in download stage
- Timeline filtering via `--min-match-quality` flag
- Priority-based track assignment (high-priority entities on lower/more visible tracks)
- Result explanation logging (differentiator)

**Addresses:**
- Result explanation feature (differentiator)
- Quality-based filtering in timeline generation

**Avoids:**
- Silent failures via quality tracking and logging

**Research flag:** Skip `/gsd:research-phase` — straightforward implementation of quality metadata usage.

### Phase Ordering Rationale

- **Sequential dependency:** Each phase builds on previous. Enrichment infrastructure must exist before search strategies can be generated. Search strategies must work before disambiguation makes sense.

- **Risk management:** Early phases (1-3) have low LLM complexity and clear validation paths. Complex LLM work (disambiguation) deferred to Phase 4 after foundation proven.

- **Incremental value:** Each phase delivers measurable improvement. Phase 2 improves search success rate. Phase 3 reduces wasted downloads. Phase 4 improves accuracy. Phase 5 adds visibility.

- **Pitfall avoidance:** Phase 1 must include shared rate limiter (Pitfall 1) before parallel execution enabled. Phase 4 must include disambiguation detection (Pitfall 3), title validation (Pitfall 2), and context-heavy prompts (Pitfall 4).

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2:** LLM prompt engineering for search strategy generation. Token optimization. Batch API usage patterns.
- **Phase 4:** LLM prompt engineering for disambiguation. Wikipedia API disambiguation detection patterns. Caching strategies for persistent disambiguation memory. Testing strategy for ambiguous entities.

**Phases with standard patterns (skip research-phase):**
- **Phase 1:** File I/O, data structure augmentation, deterministic priority scoring.
- **Phase 3:** Business logic based on entity type rules.
- **Phase 5:** Quality metadata usage in existing timeline generation.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Wikipedia API well-documented and stable. Existing code uses best practices (User-Agent, maxlag, redirects, retry logic). No changes needed. |
| Features | MEDIUM-HIGH | Wikipedia API patterns and LLM prompt engineering well-established. Disambiguation success rates need empirical validation. |
| Architecture | HIGH | Existing codebase analysis shows clear extension points. Four-stage pipeline maintains checkpoint-based design. Build order proven in similar projects. |
| Pitfalls | HIGH | Three critical pitfalls identified with clear mitigation strategies. Rate limiting, hallucination validation, and disambiguation detection all have established solutions. |

**Overall confidence:** MEDIUM-HIGH

Research is comprehensive for architecture and stack decisions. Primary uncertainty is LLM disambiguation accuracy on real transcript data (needs A/B testing during Phase 4 implementation).

### Gaps to Address

- **How much context is optimal?** 5 sentences? 10? Entire cue? Adjacent cues? Needs A/B testing with real transcripts during Phase 2/4 implementation.

- **Disambiguation success rates:** Research provides patterns but actual accuracy (target: 85%+ precision) needs validation dataset. Build during Phase 4: sample 50 entities from real transcript, human label correct Wikipedia page, measure precision/recall/confidence calibration.

- **Cost estimates:** Token usage estimates are rough (~$0.05 per 100 entities with GPT-4o-mini). Need real usage data to validate. Monitor during Phase 2/4 rollout.

- **Should disambiguation be entity-type aware?** People vs places vs events may need different strategies. Defer decision until Phase 4 when base disambiguation approach validated. If <70% success, revisit.

- **Wikidata for disambiguation?** Wikidata has canonical entity IDs that could improve accuracy but adds complexity (new API). Defer to post-MVP unless Wikipedia-only approach shows <70% success in Phase 4 testing.

## Sources

### Primary (HIGH confidence)
- **Existing codebase analysis** — `wikipedia_image_downloader.py`, `tools/download_entities.py`, `tools/srt_entities.py`, `generate_broll_xml.py`. Verified current implementation patterns, API usage, and extension points.
- **MediaWiki API documentation** — Official patterns for search, imageinfo, disambiguation detection. Stable API (unchanged since 2015).
- **Wikipedia REST API documentation** — Modern interface for page summaries. Well-documented endpoint structure.

### Secondary (MEDIUM confidence)
- **LLM prompt engineering patterns** — Structured output prompts and entity disambiguation are established patterns in NLP literature and OpenAI documentation.
- **Wikipedia API etiquette** — User-Agent requirements, maxlag parameter, rate limit best practices from MediaWiki community guidelines.

### Tertiary (LOW confidence)
- **Disambiguation success rate estimates** (85%+ target) — Based on similar NLP tasks, not project-specific validation.
- **Cost estimates** (~$0.05/100 entities) — Rough token calculations, needs real usage validation.
- **Wikimedia Enterprise** — Confirmed not applicable (dataset mirroring, not image search enhancement), but documentation review was limited.

**Verification needed during implementation:**
- [ ] Confirm Wikipedia REST API `/page/summary/` endpoint format hasn't changed
- [ ] Verify no new paid Wikipedia image search services launched since research
- [ ] Check if MediaWiki API added new disambiguation features since 2025
- [ ] Validate LLM disambiguation accuracy on real transcript data (Phase 4)
- [ ] Measure actual token costs vs estimates (Phase 2/4)

---
*Research completed: 2026-01-25*
*Ready for roadmap: yes*
