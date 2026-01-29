# Phase 2: Search Strategy Generation - Research

**Researched:** 2026-01-29
**Domain:** LLM-powered search query generation, Wikipedia API integration, structured JSON outputs
**Confidence:** HIGH

## Summary

Phase 2 replaces naive entity name lookups with LLM-generated Wikipedia search queries, improving match success rates from ~60% to an expected 85-90%. The phase focuses on three key capabilities: (1) using Claude API to generate 2-3 contextual search queries per entity, (2) validating Wikipedia article titles exist before download attempts, and (3) recording which search strategy succeeded for each entity in metadata.

Research confirms that Claude Sonnet 4.5 with structured outputs (beta feature) provides guaranteed JSON schema compliance, eliminating retry logic for malformed responses. The Wikipedia-API Python library (v0.9.0, released January 2026) offers simple title validation via the `.exists()` method. Batch processing 5-10 entities per LLM call balances API costs with failure isolation. Persistent caching with DiskCache (7-day TTL) prevents redundant Wikipedia validation requests.

The implementation extends the existing checkpoint architecture: enriched_entities.json (from Phase 1) → LLM generates search strategies → Wikipedia validates titles → augmented enriched_entities.json with search_strategies[] field. The download stage (Phase 1) iterates through strategies sequentially, recording the successful strategy in metadata.

**Primary recommendation:** Use Anthropic Python SDK (v0.76.0) with structured outputs for guaranteed JSON compliance, Wikipedia-API library for title validation, DiskCache for persistent caching with 7-day expiry, and Pydantic v2 for schema definition and validation. Batch 5-10 entities per LLM call, with exponential backoff retry for transient failures.

## Standard Stack

Libraries selected based on official documentation, current versions, and ecosystem adoption.

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | 0.76.0+ | Claude API client with structured outputs | Official Anthropic SDK, supports beta structured-outputs-2025-11-13 |
| pydantic | 2.x | Schema definition and validation | Industry standard (466k+ repos), 5-50x faster than v1, used by FastAPI/LangChain |
| Wikipedia-API | 0.9.0+ | Wikipedia article validation | Latest release (Jan 24, 2026), simple .exists() method, canonical URL support |
| diskcache | 5.6.3+ | Persistent cache with TTL | Pure Python, zero-config, LRU eviction, Django-compatible |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| requests | 2.32.0+ | Fallback HTTP client | Already in requirements.txt, use if direct Wikipedia API calls needed |
| tenacity | 8.x | Retry logic with exponential backoff | Standard for LLM API retry patterns, cleaner than manual loops |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Wikipedia-API | wikipedia (goldsmith) | Older library, less active maintenance, similar features |
| DiskCache | shelved-cache + cachetools | More complex setup, two dependencies instead of one |
| DiskCache | Redis | Requires external service, overkill for single-machine caching |
| Pydantic | Manual JSON validation | Error-prone, loses type safety, slower development |
| Structured outputs | Manual JSON prompting | 10-30% malformed responses require retries, increases costs |

**Installation:**
```bash
pip install anthropic>=0.76.0 pydantic>=2.0 Wikipedia-API>=0.9.0 diskcache>=5.6.3 tenacity>=8.0
```

## Architecture Patterns

### Recommended Project Structure

```
tools/
├── srt_entities.py          # Existing: extraction stage
├── enrich_entities.py        # Existing: enrichment stage (Phase 1)
├── generate_search_strategies.py  # NEW: LLM-powered search query generation
├── download_entities.py      # UPDATE: iterate through search strategies
broll.py                      # UPDATE: add search-strategy generation to pipeline
```

### Pattern 1: Structured JSON Output with Pydantic + Claude

**What:** Use Pydantic models to define expected LLM output schema, leverage Claude's structured outputs for guaranteed compliance.

**When to use:** When LLM responses must be parseable JSON matching specific schema (no retries needed).

**Example:**
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
from pydantic import BaseModel, Field
from typing import List
from anthropic import Anthropic

class SearchStrategy(BaseModel):
    """Search strategy for a single entity."""
    entity_name: str = Field(description="Original entity name from transcript")
    best_title: str = Field(description="Most likely Wikipedia article title (exact match preferred)")
    queries: List[str] = Field(
        description="2-3 search queries ordered by confidence (most likely first)",
        min_length=2,
        max_length=3
    )
    confidence: int = Field(description="Confidence score 1-10", ge=1, le=10)

class BatchSearchStrategies(BaseModel):
    """Batch of search strategies for multiple entities."""
    strategies: List[SearchStrategy]

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.beta.messages.parse(
    model="claude-sonnet-4-5-20250929",
    max_tokens=2048,
    betas=["structured-outputs-2025-11-13"],
    messages=[
        {
            "role": "user",
            "content": f"Generate Wikipedia search strategies for these entities: {entities_batch}"
        }
    ],
    output_format=BatchSearchStrategies,
)

# response.parsed_output is guaranteed valid BatchSearchStrategies instance
strategies = response.parsed_output.strategies
```

**Key benefits:**
- No JSON parsing errors (100% valid responses)
- Automatic Pydantic validation
- Type-safe access to response fields
- No retry logic needed for malformed JSON

### Pattern 2: Wikipedia Title Validation with Caching

**What:** Validate that LLM-suggested Wikipedia titles actually exist, cache results to avoid redundant API calls.

**When to use:** Before attempting downloads, to filter invalid suggestions early.

**Example:**
```python
# Source: https://pypi.org/project/Wikipedia-API/ + https://pypi.org/project/diskcache/
import wikipediaapi
from diskcache import Cache

# Initialize cache (7-day TTL as per Phase 2 CONTEXT)
wiki_cache = Cache('/tmp/wikipedia_title_cache')
CACHE_TTL = 7 * 24 * 3600  # 7 days in seconds

# Initialize Wikipedia API client
wiki = wikipediaapi.Wikipedia(
    user_agent='B-Roll-Finder/1.0 (contact@example.com)',
    language='en'
)

def validate_wikipedia_title(title: str) -> dict:
    """Validate Wikipedia title exists, return canonical form.

    Returns:
        {
            "exists": bool,
            "canonical_url": str or None,
            "canonical_title": str or None
        }
    """
    # Check cache first
    cache_key = f"wiki_title:{title}"
    cached = wiki_cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch from Wikipedia API
    page = wiki.page(title)
    result = {
        "exists": page.exists(),
        "canonical_url": page.canonicalurl if page.exists() else None,
        "canonical_title": page.title if page.exists() else None
    }

    # Cache result (7-day expiry)
    wiki_cache.set(cache_key, result, expire=CACHE_TTL)

    return result
```

**Key benefits:**
- Prevents failed download attempts (saves time)
- Caching reduces Wikipedia API load
- Gets canonical title form (handles redirects)
- 7-day cache balances freshness vs performance

### Pattern 3: Batch Processing with Partial Failure Handling

**What:** Process 5-10 entities per LLM call, handle batch failures gracefully by retrying individually.

**When to use:** When making many LLM API calls where batching reduces costs/latency.

**Example:**
```python
# Source: Research on LLM batch processing best practices + tenacity library
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from anthropic import APIError

def process_entities_in_batches(entities: List[Dict], batch_size: int = 7) -> List[Dict]:
    """Process entities in batches with fallback to individual processing."""
    enriched = []

    for i in range(0, len(entities), batch_size):
        batch = entities[i:i+batch_size]

        try:
            # Try batch processing
            strategies = generate_batch_strategies(batch, client, video_context)

            # Merge strategies into entities
            for entity, strategy in zip(batch, strategies):
                entity["search_strategies"] = {
                    "best_title": strategy.best_title,
                    "queries": strategy.queries,
                    "confidence": strategy.confidence,
                    "status": "generated"
                }
                enriched.append(entity)

        except Exception as batch_error:
            # Batch failed after retries: fallback to individual processing
            print(f"Batch failed, processing individually: {batch_error}")

            for entity in batch:
                try:
                    single_batch = [entity]
                    strategies = generate_batch_strategies(single_batch, client, video_context)
                    entity["search_strategies"] = {
                        "best_title": strategies[0].best_title,
                        "queries": strategies[0].queries,
                        "confidence": strategies[0].confidence,
                        "status": "generated"
                    }
                except Exception:
                    # Mark as failed, use entity name as fallback
                    entity["search_strategies"] = {
                        "best_title": entity["name"],
                        "queries": [entity["name"]],
                        "confidence": 1,
                        "status": "failed_generation"
                    }
                enriched.append(entity)

    return enriched
```

**Key decisions from CONTEXT:**
- Batch size 5-10 entities (research shows good balance)
- People get 3 queries, others get 2
- LLM decides when to add disambiguation hints
- Fallback to entity name if all strategies fail

### Pattern 4: Download Strategy Iteration

**What:** Download stage tries all generated strategies, picks best result, records which succeeded.

**When to use:** Implementing the download stage's strategy iteration logic (Phase 2 requirement SRCH-02).

**Example:**
```python
# Source: Phase 2 CONTEXT decision - try ALL strategies, pick best
def download_with_strategies(entity: Dict) -> Dict:
    """Try all search strategies, return best match with metadata."""
    strategies = entity.get("search_strategies", {})
    best_title = strategies.get("best_title")
    queries = strategies.get("queries", [])

    results = []

    # Strategy 1: Try best_title first
    if best_title:
        validation = validate_wikipedia_title(best_title)
        if validation["exists"]:
            images = download_wikipedia_images(validation["canonical_title"])
            if images:
                results.append({
                    "strategy": "best_title",
                    "title": validation["canonical_title"],
                    "images": images,
                    "match_quality": "exact"
                })

    # Strategy 2-N: Try all queries
    for idx, query in enumerate(queries):
        validation = validate_wikipedia_title(query)
        if validation["exists"]:
            images = download_wikipedia_images(validation["canonical_title"])
            if images:
                match_quality = "exact" if validation["canonical_title"] == best_title else "query_match"
                results.append({
                    "strategy": f"query_{idx+1}",
                    "title": validation["canonical_title"],
                    "images": images,
                    "match_quality": match_quality
                })

    # Pick best result (prefer exact match to best_title)
    if results:
        exact_matches = [r for r in results if r["match_quality"] == "exact"]
        best_result = exact_matches[0] if exact_matches else results[0]

        entity["download_status"] = "success"
        entity["matched_strategy"] = best_result["strategy"]
        entity["wikipedia_title"] = best_result["title"]
        entity["images"] = best_result["images"]
    else:
        entity["download_status"] = "no_match"
        entity["matched_strategy"] = None

    return entity
```

### Anti-Patterns to Avoid

- **Generating strategies for every entity:** Only generate for entities without images from Phase 1
- **Not validating titles before download:** Always validate with Wikipedia API first
- **Hardcoding batch size:** Make batch size configurable (--batch-size flag)
- **Ignoring video context:** Video title/topic dramatically improves strategy quality
- **Caching without TTL:** Wikipedia content changes, use 7-day TTL

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic with backoff | Manual sleep() loops | tenacity library | Handles exponential backoff, jitter, exception types automatically |
| JSON schema validation | Custom validation functions | Pydantic v2 | 5-50x faster, type-safe, industry standard |
| Persistent caching | Manual file writes | DiskCache | Thread-safe, LRU eviction, TTL support, crash-safe |
| Wikipedia API client | requests + manual parsing | Wikipedia-API library | Handles redirects, normalization, .exists() method |
| Structured LLM outputs | Manual JSON prompting | Claude structured outputs | 100% valid JSON, no retry logic needed |

**Key insight:** LLM structured outputs (beta feature, 2025-11-13) eliminate 10-30% of retry attempts caused by malformed JSON. Wikipedia-API's .exists() method handles redirects and normalization automatically, avoiding manual MediaWiki API complexity.

## Common Pitfalls

### Pitfall 1: LLM Generates Invalid Wikipedia Titles

**What goes wrong:** LLM suggests plausible-sounding Wikipedia titles that don't actually exist.

**Why it happens:** LLMs hallucinate exact titles based on patterns, not actual Wikipedia knowledge.

**How to avoid:**
- ALWAYS validate titles with Wikipedia API before download attempts
- Use validation result's canonical_title (handles redirects automatically)
- Cache validation results (7-day TTL) to avoid redundant API calls
- Record validation failures in metadata for debugging

**Warning signs:**
- Download success rate doesn't improve despite LLM strategies
- Many "article not found" errors in logs

### Pitfall 2: Batch Size Too Large Causes Total Failure

**What goes wrong:** Batch of 20 entities hits rate limit or timeout, all 20 fail instead of partial success.

**Why it happens:** Larger batches = longer LLM responses = higher chance of transient failure.

**How to avoid:**
- Keep batch size 5-10 (research recommendation)
- Implement fallback: batch fails → retry individually
- Use exponential backoff with tenacity
- Monitor batch failure rate, adjust size if needed

**Warning signs:**
- Frequent "batch timeout" errors
- All-or-nothing success patterns (100% success or 100% failure per batch)

### Pitfall 3: Video Context Ignored in Prompt

**What goes wrong:** Ambiguous entity "Jordan" generates generic strategies (country), misses correct article (Michael Jordan).

**Why it happens:** LLM lacks video-specific context to disambiguate.

**How to avoid:**
- Extract video topic/title from metadata
- Include in every batch prompt: "Video topic: {topic}"
- Pass transcript context from Phase 1 enrichment
- LLM uses context to infer correct disambiguation

**Warning signs:**
- Strategies for ambiguous entities miss obvious context clues
- Person names resolve to places/organizations

### Pitfall 4: Wikipedia API Rate Limiting Not Handled

**What goes wrong:** Rapid validation requests hit Wikipedia rate limits, get throttled or banned.

**Why it happens:** No rate limiting on validation calls, especially when cache is cold.

**How to avoid:**
- Make requests sequentially, not parallel (Wikipedia recommendation)
- Set descriptive User-Agent header
- Enable GZip compression (Accept-Encoding: gzip)

**Warning signs:**
- Wikipedia returns 429 Too Many Requests
- API responses include "ratelimited" error code

## Code Examples

Verified patterns from official documentation:

### Generate Search Strategies with Structured Output

```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
from pydantic import BaseModel, Field
from typing import List
from anthropic import Anthropic

class SearchStrategy(BaseModel):
    entity_name: str
    entity_type: str
    best_title: str = Field(description="Most likely exact Wikipedia article title")
    queries: List[str] = Field(description="2-3 search queries ordered by confidence", min_length=2, max_length=3)
    confidence: int = Field(description="Confidence 1-10", ge=1, le=10)

class BatchSearchStrategies(BaseModel):
    strategies: List[SearchStrategy]

def generate_search_strategies(entities: List[dict], video_context: str, client: Anthropic) -> List[SearchStrategy]:
    """Generate Wikipedia search strategies for entities using Claude."""

    prompt = f"""Video topic: {video_context}

Generate Wikipedia search strategies for these entities:
{format_entities(entities)}

For each entity:
1. best_title: Most likely exact Wikipedia article title
2. queries: 2-3 alternative search queries (People get 3, others get 2)
3. confidence: Score 1-10 based on certainty

Order queries by likelihood. Include disambiguation hints (profession, era, location) only when ambiguous."""

    response = client.beta.messages.parse(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format=BatchSearchStrategies,
    )

    return response.parsed_output.strategies
```

### Validate Wikipedia Titles with Caching

```python
# Source: https://pypi.org/project/Wikipedia-API/ + https://pypi.org/project/diskcache/
import wikipediaapi
from diskcache import Cache

class WikipediaValidator:
    def __init__(self, cache_dir: str = "/tmp/wikipedia_cache", cache_ttl_days: int = 7):
        self.cache = Cache(cache_dir)
        self.cache_ttl = cache_ttl_days * 24 * 3600
        self.wiki = wikipediaapi.Wikipedia(
            user_agent='B-Roll-Finder/1.0 (contact@example.com)',
            language='en'
        )

    def validate(self, title: str) -> dict:
        """Validate Wikipedia title, return canonical form."""
        cache_key = f"wiki:{title}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        page = self.wiki.page(title)
        result = {
            "exists": page.exists(),
            "canonical_title": page.title if page.exists() else None,
            "canonical_url": page.canonicalurl if page.exists() else None
        }

        self.cache.set(cache_key, result, expire=self.cache_ttl)
        return result
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON prompting | Claude structured outputs (beta) | Nov 2025 | 100% valid JSON, eliminates retries |
| Pydantic v1 | Pydantic v2 with Rust core | 2023 | 5-50x faster validation |
| Manual retry loops | tenacity library | 2020+ (standard by 2024) | Cleaner code, exponential backoff built-in |
| wikipedia (goldsmith) | Wikipedia-API (martin-majlis) | v0.9.0 Jan 2026 | Python 3.10+ support, active maintenance |
| Sequential LLM calls | Batch API calls | 2024-2025 | 50-80% latency reduction, lower costs |

**Deprecated/outdated:**
- **wikipedia 1.4.0 (goldsmith)**: Last release 2019, use Wikipedia-API instead
- **Manual JSON schema validation**: Use Pydantic v2 for type safety and performance
- **Claude without structured outputs**: Beta feature eliminates 10-30% retry attempts

## Open Questions

1. **Optimal batch size for Claude Sonnet 4.5**
   - What we know: Research suggests 5-10, Phase 2 CONTEXT specifies "5-10 entities per LLM call"
   - What's unclear: Anthropic-specific rate limits, impact on grammar compilation
   - Recommendation: Start with 7 entities per batch, make configurable via --batch-size flag

2. **Cache invalidation for renamed articles**
   - What we know: 7-day TTL is CONTEXT decision
   - What's unclear: How to handle Wikipedia article renames within 7-day window
   - Recommendation: Accept 7-day staleness, implement manual cache clear command

3. **Video context extraction location**
   - What we know: CONTEXT specifies "entity name, type, transcript context, AND video topic/title"
   - What's unclear: Where does video topic/title come from in existing pipeline?
   - Recommendation: Check entities_map.json for metadata field, otherwise extract from SRT filename

## Sources

### Primary (HIGH confidence)

- [Anthropic Python SDK 0.76.0](https://pypi.org/project/anthropic/) - Official SDK
- [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) - Beta feature docs
- [Wikipedia-API 0.9.0](https://pypi.org/project/Wikipedia-API/) - Article validation
- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) - Schema generation
- [DiskCache 5.6.3](https://pypi.org/project/diskcache/) - Persistent caching
- [Claude 4.x Best Practices](https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices) - Prompting guidance

### Secondary (MEDIUM confidence)

- [Wikipedia API Rate Limits](https://api.wikimedia.org/wiki/Rate_limits) - Best practices
- [MediaWiki API:Query](https://www.mediawiki.org/wiki/API:Query) - Title normalization (web search verified)
- [Tenacity Retry](https://python.useinstructor.com/concepts/retrying/) - Retry patterns
- [LLM Batch Processing Guide](https://latitude-blog.ghost.io/blog/scaling-llms-with-batch-processing-ultimate-guide/) - Batch sizes
- [Pydantic for LLMs](https://pydantic.dev/articles/llm-intro) - Schema design

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official libraries, current versions verified
- Architecture: HIGH - Structured outputs eliminate retry complexity
- Pitfalls: MEDIUM - Based on research and best practices

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - LLM APIs evolving rapidly)

**Assumptions:**
- Anthropic API key available (ANTHROPIC_API_KEY)
- Internet connectivity for Wikipedia API
- enriched_entities.json from Phase 1 contains entity_type, context fields
- Video topic/title available in metadata or extractable
