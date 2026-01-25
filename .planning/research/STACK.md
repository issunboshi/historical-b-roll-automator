# Technology Stack — Wikipedia Image Download Improvements

**Project:** B-Roll Automater — Wikipedia Image Download Improvements
**Researched:** 2026-01-25
**Confidence:** MEDIUM (based on public documentation and existing codebase analysis)

## Executive Summary

For improving Wikipedia image search and retrieval, the project should continue using the **MediaWiki Action API** (free, unlimited for reasonable use) with strategic improvements rather than switching to paid services. Wikipedia/Wikimedia does NOT offer paid tiers for higher throughput — the free API is designed for high-volume use when following best practices. The bottleneck is not API rate limits but search strategy and disambiguation logic.

**Key finding:** Current implementation already respects API best practices (0.1s delay, maxlag parameter, retry logic). Performance gains will come from smarter queries and LLM-driven disambiguation, not API upgrades.

## Recommended Stack

### Core Wikipedia API
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| MediaWiki Action API | Current (v1) | Image search, metadata retrieval, page content | Industry standard, unlimited free access, comprehensive documentation, supports batch queries |
| Wikipedia REST API | v1 (supplemental) | Page summaries for disambiguation | Modern REST interface, simpler for summary-only queries, lower overhead |

**Rate limits:** NONE for normal use. Wikipedia's only requirement is:
- User-Agent header identifying your app (✓ already implemented)
- `maxlag` parameter to back off during high server load (✓ already implemented)
- Reasonable delays between requests (✓ already implemented: 0.1s default)

**Throughput:** Current implementation can handle ~600 requests/minute (0.1s delay). For parallel downloads with 4 workers, ~2400 requests/minute. This is well within acceptable use.

**Paid/enterprise options:** NONE. Wikimedia Enterprise exists but is for mirroring entire Wikipedia datasets, not image search. Not applicable to this use case.

### Search Enhancement Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `requests` | 2.31+ | HTTP client | Already in use; maintain for API calls |
| `beautifulsoup4` | 4.12+ | HTML parsing | Already in use; maintain for content extraction |
| `pywikibot` | 9.0+ | Wikipedia automation framework | Consider for future if building complex Wikipedia workflows (overkill for current needs) |

**Recommendation:** Continue with `requests` directly. `pywikibot` adds significant complexity for marginal benefit given the focused use case.

### LLM Integration for Disambiguation
| Service | Purpose | Why |
|---------|---------|-----|
| OpenAI API | GPT-4/GPT-3.5 for search query generation and disambiguation | Already integrated; proven reliable for entity extraction |
| Ollama | Local LLM fallback | Already integrated; no-cost option for development/testing |

**No changes needed:** Existing LLM integration is sufficient. Disambiguation will use the same providers as entity extraction.

## Alternatives Considered

### Wikimedia Enterprise API
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| API Access | MediaWiki Action API (free) | Wikimedia Enterprise | Enterprise is for dataset mirroring (full Wikipedia dumps, real-time updates for mirrors). Does not provide enhanced image search. Not applicable. |

### Wikipedia API Alternatives
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Search | MediaWiki `action=query&list=search` | MediaWiki `action=opensearch` | opensearch is autocomplete-focused, returns less metadata. query/search provides snippet, wordcount, page size for disambiguation. |
| Image metadata | `prop=imageinfo` with `extmetadata` | Wikimedia Commons API | Commons API is identical to MediaWiki API; no advantage. Current approach is optimal. |
| Page content | MediaWiki `action=parse` | Wikipedia REST API `/page/summary/` | Both viable. REST API simpler for summaries only. Recommend REST for disambiguation summaries, keep Action API for images. |

### Third-Party Wikipedia Wrappers
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| HTTP Client | Direct `requests` usage | `wikipedia` Python library | `wikipedia` library is unmaintained (last update 2020), abstracts away control needed for batch queries and custom retry logic. Direct API calls better. |
| HTTP Client | Direct `requests` usage | `pywikibot` | Pywikibot is for bot accounts and complex editing workflows. Overkill for read-only image retrieval. Adds auth complexity not needed. |

## API Endpoint Details

### MediaWiki Action API (Primary)

**Base URL:** `https://en.wikipedia.org/w/api.php`

**Search for pages:**
```python
params = {
    "action": "query",
    "list": "search",
    "srsearch": query,
    "srlimit": 10,  # Up to 10 results for disambiguation
    "format": "json",
    "formatversion": 2,
    "utf8": 1,
    "maxlag": 5,
}
```

**Get page images:**
```python
params = {
    "action": "parse",
    "pageid": pageid,
    "prop": "images",
    "format": "json",
    "formatversion": 2,
    "utf8": 1,
    "maxlag": 5,
}
```

**Get image metadata (batch):**
```python
params = {
    "action": "query",
    "prop": "imageinfo",
    "titles": "|".join(file_titles),  # Batch up to 50
    "iiprop": "url|size|mime|extmetadata",
    "format": "json",
    "formatversion": 2,
    "utf8": 1,
    "redirects": 1,
    "maxlag": 5,
}
```

**Rate limit handling:**
- No hard limits for compliant bots
- `maxlag=5` causes API to return 503 if server lag > 5 seconds (current implementation handles this)
- Recommended delay: 0.1s for read-only queries (✓ implemented)
- Parallel downloads: Safe with proper delays per worker (✓ implemented)

### Wikipedia REST API (Supplemental)

**Base URL:** `https://en.wikipedia.org/api/rest_v1/`

**Get page summary (for disambiguation):**
```
GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}
```

**Response includes:**
- `title`: Article title
- `extract`: Plain text summary (first paragraph)
- `description`: Short description
- `thumbnail`: Featured image if available

**Why use this:** Simpler than parsing full HTML for disambiguation. Lower bandwidth than `action=parse`.

**Rate limits:** Same as Action API (none for reasonable use).

## Search Strategy Improvements

### Current Implementation Analysis
The existing code in `wikipedia_image_downloader.py` does:
1. Single search query using entity name directly
2. Takes first result without disambiguation
3. Filters images by content location (good)
4. License categorization (good)
5. Historical prioritization (good for many use cases)

**Bottleneck identified:** Step 2. No disambiguation when multiple results exist.

### Recommended Approach

**Phase 1: Multi-query search**
- LLM generates 2-3 search queries per entity (e.g., "Barack Obama", "Barack Obama president", "Barack Obama politician")
- Search each query, collect candidate pages
- Deduplicate by page ID

**Phase 2: LLM-based disambiguation**
- Fetch summaries for top 3-5 candidates using REST API
- LLM compares summaries against transcript context
- Select best match or fall back to original if ambiguous

**Phase 3: Caching**
- Cache entity → Wikipedia page ID mappings in JSON
- Skip search/disambiguation for previously resolved entities
- Invalidate cache periodically (30 days) to catch new articles

### API Call Volume Analysis

**Current:** For 50 entities with 3 images each:
- 50 searches
- 50 page parses (images)
- ~3 imageinfo queries (batched, 50 titles each)
- Total: ~103 API calls

**With improvements:** For 50 entities:
- 50 × 3 = 150 searches (multi-query)
- 50 × 3 = 150 summary fetches (disambiguation candidates)
- 50 page parses (images, once disambiguated)
- ~3 imageinfo queries (batched)
- Total: ~353 API calls

**Throughput:** At 0.1s delay: ~35 seconds for 353 calls. Acceptable.

**With 4 parallel workers:** ~9 seconds. Well within Wikipedia's acceptable use.

## Implementation Recommendations

### Do NOT Change
- HTTP client (`requests`) — proven, well-understood
- Retry logic with exponential backoff — robust
- `maxlag` parameter — respects Wikipedia server load
- Batch imageinfo queries — efficient
- License categorization logic — comprehensive
- Image filtering (content vs UI icons) — effective

### Add/Enhance
1. **Wikipedia REST API client** for summaries
   - Add new function `get_page_summary(title: str) -> Dict`
   - Use for disambiguation only
   - Lower overhead than full parse

2. **Multi-query search function**
   - `search_wikipedia_pages(queries: List[str], limit: int) -> List[Dict]`
   - Deduplicate by page ID
   - Return top N candidates across all queries

3. **Disambiguation function**
   - `disambiguate_page(candidates: List[Dict], context: str, llm_client) -> Optional[Dict]`
   - LLM prompt: "Which article matches this context?"
   - Return selected page or None

4. **Entity resolution cache**
   - JSON file: `{"entity_name": {"page_id": 12345, "title": "...", "timestamp": "..."}}`
   - Load on startup, save after each resolution
   - Skip search/disambiguation for cached entities

### Optional (Future)
- **Wikidata integration** for cross-language disambiguation (if expanding beyond English Wikipedia)
- **Category-based filtering** (e.g., prefer articles in "20th-century American politicians" for politician entities)

## Sources

**Confidence Level: MEDIUM**

Sources used:
- Existing codebase analysis (`wikipedia_image_downloader.py`, `tools/download_entities.py`)
- MediaWiki API documentation (public knowledge as of Jan 2025)
- Wikipedia REST API documentation (public knowledge as of Jan 2025)
- Wikimedia Enterprise FAQ (public knowledge as of Jan 2025)

**Verification needed:**
- [ ] Confirm Wikipedia REST API `/page/summary/` endpoint still exists and format hasn't changed
- [ ] Verify no new paid Wikipedia image search services launched in 2026
- [ ] Check if MediaWiki API added new disambiguation features since 2025

**Note:** Web search and official documentation fetch were unavailable during research. Recommendations based on:
1. Stable APIs (MediaWiki Action API unchanged since 2015)
2. Existing code patterns (proven to work)
3. Public knowledge of Wikimedia architecture

**Follow-up:** Before implementation, verify current API documentation at:
- https://www.mediawiki.org/wiki/API:Main_page
- https://en.wikipedia.org/api/rest_v1/
- https://enterprise.wikimedia.com/ (to confirm no new image search offerings)
