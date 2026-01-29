# Phase 4: Disambiguation - Research

**Researched:** 2026-01-29
**Domain:** Wikipedia disambiguation, LLM-powered entity matching, confidence scoring
**Confidence:** HIGH

## Summary

Phase 4 implements intelligent disambiguation when Wikipedia searches return multiple potential matches. The core challenge is selecting the contextually correct Wikipedia article from multiple candidates based on transcript context, then assigning confidence scores to enable auto-acceptance of high-confidence matches and flagging uncertain ones for review.

Research confirms that the existing stack (Claude with structured outputs, Wikipedia-API library, DiskCache) provides all necessary capabilities. The disambiguation workflow extends the Phase 2 search strategy architecture: (1) Wikipedia API returns top 3 candidates per query, (2) fetch summary + categories for each candidate, (3) Claude compares candidates against transcript context and selects best match with confidence score, (4) disambiguation pages are detected via the `pageprops` API and resolved by extracting linked articles.

The key technical insights are: (1) Wikipedia's `prop=pageprops&ppprop=disambiguation` API reliably detects disambiguation pages (empty string value indicates disambig), (2) Claude's structured outputs (beta) provide guaranteed JSON compliance for disambiguation decisions, eliminating retry logic, (3) confidence scoring should use LLM-generated scores with clear rubric in prompt rather than relying on log probabilities (which are unreliable for this use case), and (4) the review workflow uses JSON files for human oversight and manual override capability.

**Primary recommendation:** Extend `generate_search_strategies.py` to add a disambiguation module using Claude structured outputs with Pydantic schemas. Use direct MediaWiki API calls (not Wikipedia-API) for disambiguation page detection since `pageprops` API is not exposed by the Wikipedia-API library. Cache disambiguation decisions with DiskCache (7-day TTL). Implement depth-limited recursive resolution for disambiguation pages.

## Standard Stack

Libraries selected based on existing project stack, official documentation, and current versions.

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | 0.76.0+ | Claude API client with structured outputs | Already in project (Phase 2), supports beta structured-outputs-2025-11-13 |
| pydantic | 2.x | Schema definition for disambiguation decisions | Already in project (Phase 2), type-safe, 5-50x faster than v1 |
| requests | 2.32.0+ | Direct MediaWiki API calls for pageprops | Already in project, needed for disambiguation page detection |
| Wikipedia-API | 0.9.0+ | Page summaries, categories, validation | Already in project (Phase 2), simple .exists() and .summary methods |
| diskcache | 5.6.3+ | Persistent cache for disambiguation results | Already in project (Phase 2), 7-day TTL per CONTEXT decision |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | 8.x | Retry logic for API calls | Already in project (Phase 2), exponential backoff for transient failures |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct requests for pageprops | Wikipedia-API | Wikipedia-API doesn't expose pageprops; direct API is simple |
| LLM confidence scores | Log probabilities | Research shows self-reported LLM scores work better for disambiguation decisions |
| JSON review files | SQLite database | JSON is simpler, human-readable, matches project conventions |

**Installation:**
```bash
# No new dependencies - all already in project from Phase 2
pip install anthropic>=0.76.0 pydantic>=2.0 Wikipedia-API>=0.9.0 diskcache>=5.6.3 tenacity>=8.0 requests>=2.32.0
```

## Architecture Patterns

### Recommended Project Structure

```
tools/
    generate_search_strategies.py    # Existing: search strategy generation (Phase 2)
    disambiguation.py                # NEW: disambiguation module
    download_entities.py             # UPDATE: integrate disambiguation results
output/
    disambiguation_review.json       # NEW: flagged entities for human review
    disambiguation_overrides.json    # NEW: manual override mappings
```

### Pattern 1: Disambiguation Decision with Structured Output

**What:** Use Claude structured outputs to select best Wikipedia candidate with confidence score.

**When to use:** When 2+ Wikipedia candidates exist for an entity and disambiguation is needed.

**Example:**
```python
# Source: Claude structured outputs docs + project conventions
from pydantic import BaseModel, Field
from typing import List, Optional
from anthropic import Anthropic

class CandidateInfo(BaseModel):
    """Information about a Wikipedia candidate."""
    title: str = Field(description="Wikipedia article title")
    summary: str = Field(description="First paragraph summary")
    categories: List[str] = Field(description="Top categories (max 5)")

class DisambiguationDecision(BaseModel):
    """Disambiguation decision for a single entity."""
    entity_name: str = Field(description="Original entity name from transcript")
    chosen_article: str = Field(description="Selected Wikipedia article title")
    confidence: int = Field(description="Confidence score 0-10", ge=0, le=10)
    rationale: str = Field(description="Brief explanation of why this article was chosen")
    match_quality: str = Field(
        description="Match quality assessment",
        enum=["high", "medium", "low", "none"]
    )
    candidates_considered: List[str] = Field(description="All candidate titles that were compared")

def disambiguate_entity(
    entity_name: str,
    entity_type: str,
    transcript_context: str,
    candidates: List[CandidateInfo],
    video_topic: str,
    client: Anthropic
) -> DisambiguationDecision:
    """Use Claude to select best Wikipedia candidate."""

    # Format candidates for prompt
    candidate_text = "\n\n".join([
        f"Candidate {i+1}: {c.title}\n"
        f"Summary: {c.summary}\n"
        f"Categories: {', '.join(c.categories[:5])}"
        for i, c in enumerate(candidates)
    ])

    prompt = f"""Video topic: {video_topic}

Entity to disambiguate: {entity_name} (type: {entity_type})

Transcript context where entity appears:
"{transcript_context}"

Wikipedia candidates:
{candidate_text}

Select the best matching Wikipedia article for this entity.

Scoring guidelines:
- Confidence 8-10: Clear match, article directly about the entity in this context
- Confidence 5-7: Likely match but some ambiguity remains
- Confidence 2-4: Uncertain, multiple candidates could fit
- Confidence 0-1: No good match found

Match quality:
- high: Single obvious match or confident disambiguation (confidence >= 7)
- medium: Successful disambiguation with moderate confidence (4-6)
- low: All strategies uncertain but got some result (confidence 1-3)
- none: No match found (confidence 0)

Consider:
1. Does the candidate summary match the transcript context?
2. Is the entity type consistent (person mentioned in transcript should match person article)?
3. Does the video topic provide disambiguation hints?"""

    response = client.beta.messages.parse(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format=DisambiguationDecision,
    )

    return response.parsed_output
```

### Pattern 2: Wikipedia Search with Multiple Candidates

**What:** Fetch top 3 Wikipedia search results for an entity query.

**When to use:** Replacing single-result search with multi-candidate search.

**Example:**
```python
# Source: MediaWiki API:Search documentation
import requests

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

def search_wikipedia_candidates(
    session: requests.Session,
    query: str,
    limit: int = 3
) -> List[dict]:
    """Search Wikipedia and return top N candidates.

    Returns:
        List of dicts with keys: pageid, title, snippet
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,  # Get multiple results
        "srprop": "snippet",  # Include search snippet
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
        "maxlag": 5,
    }

    resp = session.get(WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("query", {}).get("search", [])
    return [
        {
            "pageid": r.get("pageid"),
            "title": r.get("title"),
            "snippet": r.get("snippet", "")
        }
        for r in results
    ]
```

### Pattern 3: Disambiguation Page Detection

**What:** Check if a Wikipedia page is a disambiguation page using pageprops API.

**When to use:** Before attempting to download images from a page, detect and resolve disambiguation pages.

**Example:**
```python
# Source: MediaWiki Extension:Disambiguator, API:Pageprops documentation
def is_disambiguation_page(
    session: requests.Session,
    title: str
) -> bool:
    """Check if page is a disambiguation page using pageprops API.

    Note: The 'disambiguation' property is an empty string when present,
    so check for key existence, not truthiness.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageprops",
        "ppprop": "disambiguation",
        "format": "json",
        "formatversion": 2,
    }

    resp = session.get(WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return False

    page = pages[0]
    pageprops = page.get("pageprops", {})

    # Key insight: disambiguation prop is EMPTY STRING when present
    # Must check key existence, not value
    return "disambiguation" in pageprops


def extract_disambiguation_links(
    session: requests.Session,
    title: str,
    limit: int = 5
) -> List[str]:
    """Extract article links from a disambiguation page.

    Uses prop=links to get internal links, filters to main namespace.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "links",
        "pllimit": limit * 2,  # Fetch extra to filter
        "plnamespace": 0,  # Main namespace only
        "format": "json",
        "formatversion": 2,
    }

    resp = session.get(WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return []

    links = pages[0].get("links", [])
    return [link["title"] for link in links[:limit]]
```

### Pattern 4: Depth-Limited Disambiguation Resolution

**What:** Recursively resolve disambiguation pages with depth limit to prevent infinite loops.

**When to use:** When a search result is a disambiguation page.

**Example:**
```python
# Source: CONTEXT.md decision - max 3 disambiguation attempts
def resolve_disambiguation(
    session: requests.Session,
    entity_name: str,
    initial_title: str,
    transcript_context: str,
    video_topic: str,
    client: Anthropic,
    max_depth: int = 3,
    current_depth: int = 0
) -> Optional[DisambiguationDecision]:
    """Resolve disambiguation page with depth limit.

    Args:
        max_depth: Maximum disambiguation attempts (default 3 per CONTEXT)
        current_depth: Current recursion depth

    Returns:
        DisambiguationDecision or None if all attempts failed
    """
    if current_depth >= max_depth:
        print(f"Max disambiguation depth reached for {entity_name}")
        return None

    # Check if this is a disambiguation page
    if not is_disambiguation_page(session, initial_title):
        # Not a disambiguation page - return as valid result
        return DisambiguationDecision(
            entity_name=entity_name,
            chosen_article=initial_title,
            confidence=7,  # Single result, moderate confidence
            rationale="Direct match, not a disambiguation page",
            match_quality="medium",
            candidates_considered=[initial_title]
        )

    # Extract links from disambiguation page
    linked_titles = extract_disambiguation_links(session, initial_title, limit=5)

    if not linked_titles:
        return None

    # Fetch summaries for linked articles
    candidates = []
    for title in linked_titles:
        # Check if this linked article is ALSO a disambiguation page
        if is_disambiguation_page(session, title):
            # Skip nested disambiguation pages
            continue

        # Fetch summary and categories
        wiki = wikipediaapi.Wikipedia(
            user_agent='B-Roll-Finder/1.0',
            language='en'
        )
        page = wiki.page(title)
        if page.exists():
            candidates.append(CandidateInfo(
                title=title,
                summary=page.summary[:500],  # First 500 chars
                categories=list(page.categories.keys())[:5]
            ))

    if not candidates:
        return None

    # Use LLM to select best candidate
    decision = disambiguate_entity(
        entity_name=entity_name,
        entity_type="",  # Could be passed in
        transcript_context=transcript_context,
        candidates=candidates,
        video_topic=video_topic,
        client=client
    )

    # Recursively check if chosen article is also a disambiguation page
    if is_disambiguation_page(session, decision.chosen_article):
        return resolve_disambiguation(
            session, entity_name, decision.chosen_article,
            transcript_context, video_topic, client,
            max_depth, current_depth + 1
        )

    return decision
```

### Pattern 5: Review File Generation

**What:** Generate JSON review file for entities flagged for human review.

**When to use:** When disambiguation confidence is 4-6 (needs review).

**Example:**
```python
# Source: CONTEXT.md decision - dedicated review file
import json
from pathlib import Path

class DisambiguationReviewEntry(BaseModel):
    """Entry for human review of uncertain disambiguation."""
    entity_name: str
    candidates: List[dict]  # All candidates with summaries
    chosen_article: str
    confidence: int
    rationale: str
    transcript_context: str
    video_topic: str

def write_review_file(
    entries: List[DisambiguationReviewEntry],
    output_path: Path
) -> None:
    """Write disambiguation review file for human oversight.

    Only includes entities with confidence 4-6 (needs review).
    """
    review_data = {
        "generated": datetime.datetime.now().isoformat(),
        "instructions": (
            "Review entities below where disambiguation was uncertain. "
            "To override, add entry to disambiguation_overrides.json with format: "
            '{"entity_name": "Correct_Wikipedia_Article_Title"}'
        ),
        "entities": [entry.model_dump() for entry in entries]
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)


def load_overrides(override_path: Path) -> dict:
    """Load manual disambiguation overrides.

    Override file format: {"entity_name": "Wikipedia_Article_Title"}
    """
    if not override_path.exists():
        return {}

    with open(override_path, "r", encoding="utf-8") as f:
        return json.load(f)
```

### Anti-Patterns to Avoid

- **Downloading disambiguation pages directly:** Always detect and resolve before download
- **Unbounded recursion:** Always enforce max_depth (3 per CONTEXT decision)
- **Trusting single search result:** Even single results should check for disambiguation page
- **Ignoring transcript context:** Context is crucial for correct disambiguation
- **Relying on log probabilities for confidence:** LLM self-reported scores with clear rubric work better

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema validation | Manual dict checking | Pydantic v2 | Type-safe, fast, auto-validation |
| Retry logic | sleep() loops | tenacity library | Handles backoff, jitter, exception types |
| Wikipedia validation | Manual page checking | Wikipedia-API .exists() | Handles redirects automatically |
| Structured LLM output | Manual JSON parsing | Claude structured outputs | 100% valid JSON, no retries needed |
| Persistent caching | File-based manual cache | DiskCache | Thread-safe, TTL, crash-safe |

**Key insight:** The Phase 2 stack (Claude structured outputs + Wikipedia-API + DiskCache + tenacity) provides all required infrastructure. Phase 4 extends rather than replaces.

## Common Pitfalls

### Pitfall 1: Disambiguation Page Property is Empty String

**What goes wrong:** Code checks `if pageprops.get("disambiguation"):` which fails because the value is an empty string.

**Why it happens:** MediaWiki returns disambiguation as an empty string, not a boolean true.

**How to avoid:**
- Check for key existence: `"disambiguation" in pageprops`
- Do NOT check value truthiness: `pageprops.get("disambiguation")` returns empty string which is falsy

**Warning signs:**
- Disambiguation pages being downloaded directly
- Missing images for ambiguous entities

### Pitfall 2: LLM Confidence Scores Unreliable Without Rubric

**What goes wrong:** LLM returns random confidence numbers that don't correlate with actual certainty.

**Why it happens:** Research shows self-reported LLM confidence is "highly unreliable" without clear guidelines.

**How to avoid:**
- Include explicit confidence rubric in prompt (8-10 = clear match, 5-7 = likely, 2-4 = uncertain, 0-1 = no match)
- Map confidence to concrete match_quality outcomes
- Use structured output to enforce integer range

**Warning signs:**
- All confidence scores clustered around same value
- Low confidence scores for obvious matches

### Pitfall 3: Infinite Disambiguation Loops

**What goes wrong:** Disambiguation page links to another disambiguation page, which links back or to a third, creating infinite recursion.

**Why it happens:** Wikipedia disambiguation pages can form cycles.

**How to avoid:**
- Enforce max_depth limit (3 per CONTEXT decision)
- Track visited pages to prevent cycles
- Fail gracefully when depth exceeded

**Warning signs:**
- Timeouts on specific entities
- Stack overflow errors

### Pitfall 4: Single Result Assumed to be Correct

**What goes wrong:** Single search result is used without checking if it's a disambiguation page or actually relevant.

**Why it happens:** Assumption that single result = unambiguous.

**How to avoid:**
- Always check if single result is disambiguation page
- Still fetch summary and verify relevance to context
- Consider moderate confidence (not high) for single results without disambiguation

**Warning signs:**
- Wrong images for entities with common names
- Disambiguation pages being downloaded

### Pitfall 5: Context Not Used in Disambiguation

**What goes wrong:** LLM disambiguates based only on entity name, ignoring transcript context.

**Why it happens:** Prompt doesn't emphasize context importance or context is truncated.

**How to avoid:**
- Include transcript context prominently in prompt
- Include video topic/title for domain hints
- Use context window from Phase 1 enrichment (already extracted)

**Warning signs:**
- "Michael Jordan" resolving to the wrong Michael Jordan despite basketball context
- Places resolving to wrong country despite geographic hints in transcript

## Code Examples

Verified patterns from official sources and project conventions.

### Fetch Summary and Categories for Multiple Candidates

```python
# Source: Wikipedia-API documentation + project conventions
import wikipediaapi

def fetch_candidate_info(
    titles: List[str],
    cache: Cache,
    cache_ttl: int = 7 * 24 * 3600
) -> List[CandidateInfo]:
    """Fetch summaries and categories for Wikipedia candidates.

    Uses caching to reduce API calls (7-day TTL per CONTEXT decision).
    """
    wiki = wikipediaapi.Wikipedia(
        user_agent='B-Roll-Finder/1.0 (automated disambiguation)',
        language='en'
    )

    candidates = []
    for title in titles:
        # Check cache first
        cache_key = f"candidate:{title}"
        cached = cache.get(cache_key)
        if cached is not None:
            candidates.append(CandidateInfo(**cached))
            continue

        # Fetch from Wikipedia
        page = wiki.page(title)
        if not page.exists():
            continue

        info = CandidateInfo(
            title=page.title,
            summary=page.summary[:500],  # First 500 chars
            categories=list(page.categories.keys())[:5]
        )

        # Cache result
        cache.set(cache_key, info.model_dump(), expire=cache_ttl)
        candidates.append(info)

    return candidates
```

### Integration with Existing Download Flow

```python
# Source: Existing download_entities.py pattern + Phase 4 requirements
def download_with_disambiguation(
    entity_name: str,
    entity_data: dict,
    session: requests.Session,
    cache: Cache,
    client: Anthropic,
    video_topic: str
) -> dict:
    """Download entity with disambiguation support.

    Workflow:
    1. Check for manual override
    2. Get top 3 search candidates
    3. If single candidate, check if disambiguation page
    4. If multiple candidates or disambiguation page, run LLM disambiguation
    5. Apply confidence-based routing (auto-accept, flag, skip)
    """
    # Check for manual override
    overrides = load_overrides(Path("disambiguation_overrides.json"))
    if entity_name in overrides:
        # Use override directly
        return {
            "wikipedia_title": overrides[entity_name],
            "disambiguation_source": "manual_override",
            "confidence": 10,
            "match_quality": "high"
        }

    # Get transcript context from enrichment
    context = entity_data.get("context", "")

    # Search for candidates
    search_strategies = entity_data.get("search_strategies", {})
    best_title = search_strategies.get("best_title", entity_name)

    candidates = search_wikipedia_candidates(session, best_title, limit=3)

    if not candidates:
        return {
            "wikipedia_title": None,
            "disambiguation_source": "no_results",
            "confidence": 0,
            "match_quality": "none"
        }

    if len(candidates) == 1:
        # Single result - check if disambiguation page
        title = candidates[0]["title"]
        if is_disambiguation_page(session, title):
            # Resolve disambiguation page
            decision = resolve_disambiguation(
                session, entity_name, title, context, video_topic, client
            )
            if decision:
                return {
                    "wikipedia_title": decision.chosen_article,
                    "disambiguation_source": "disambiguation_page_resolved",
                    "confidence": decision.confidence,
                    "match_quality": decision.match_quality,
                    "rationale": decision.rationale,
                    "candidates_considered": decision.candidates_considered
                }
            return {
                "wikipedia_title": None,
                "disambiguation_source": "disambiguation_failed",
                "confidence": 0,
                "match_quality": "none"
            }
        else:
            # Single non-disambiguation result
            return {
                "wikipedia_title": title,
                "disambiguation_source": "single_result",
                "confidence": 7,  # Moderate confidence for single result
                "match_quality": "medium"
            }

    # Multiple candidates - run disambiguation
    candidate_infos = fetch_candidate_info(
        [c["title"] for c in candidates],
        cache
    )

    if not candidate_infos:
        return {
            "wikipedia_title": None,
            "disambiguation_source": "no_valid_candidates",
            "confidence": 0,
            "match_quality": "none"
        }

    decision = disambiguate_entity(
        entity_name=entity_name,
        entity_type=entity_data.get("entity_type", ""),
        transcript_context=context,
        candidates=candidate_infos,
        video_topic=video_topic,
        client=client
    )

    return {
        "wikipedia_title": decision.chosen_article,
        "disambiguation_source": "llm_disambiguation",
        "confidence": decision.confidence,
        "match_quality": decision.match_quality,
        "rationale": decision.rationale,
        "candidates_considered": decision.candidates_considered
    }
```

### Confidence-Based Routing

```python
# Source: CONTEXT.md decisions
def apply_confidence_routing(
    entity_name: str,
    disambiguation_result: dict,
    review_entries: List[DisambiguationReviewEntry],
    entity_data: dict,
    video_topic: str
) -> str:
    """Route entity based on disambiguation confidence.

    Returns: "download" | "flag_and_download" | "skip"

    Per CONTEXT.md decisions:
    - Confidence 7+: auto-accept, proceed with download
    - Confidence 4-6: flag as "needs review" but still use the match
    - Confidence 0-3: skip entity, mark as "no match" (no download)
    """
    confidence = disambiguation_result.get("confidence", 0)

    if confidence >= 7:
        # Auto-accept
        return "download"

    elif confidence >= 4:
        # Flag for review but still download
        review_entries.append(DisambiguationReviewEntry(
            entity_name=entity_name,
            candidates=disambiguation_result.get("candidates_considered", []),
            chosen_article=disambiguation_result.get("wikipedia_title", ""),
            confidence=confidence,
            rationale=disambiguation_result.get("rationale", ""),
            transcript_context=entity_data.get("context", ""),
            video_topic=video_topic
        ))
        return "flag_and_download"

    else:
        # Low confidence - skip (better no image than wrong image)
        return "skip"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single search result only | Multiple candidates + disambiguation | Phase 4 | Higher match accuracy |
| No disambiguation detection | pageprops API check | Standard MediaWiki | Avoid downloading disambig pages |
| Manual JSON parsing | Claude structured outputs | Nov 2025 | 100% valid JSON, no retries |
| Fixed confidence scores | LLM-generated with rubric | Current best practice | Context-aware confidence |

**Deprecated/outdated:**
- **wikipedia library (goldsmith)**: Use Wikipedia-API instead - active maintenance
- **Checking disambiguation by category name**: Use pageprops API - more reliable
- **Log probability confidence**: Use self-reported with rubric - research shows better calibration for disambiguation

## Open Questions

1. **Optimal number of candidates to fetch**
   - What we know: CONTEXT specifies "top 3 candidates per search query"
   - What's unclear: Performance impact of fetching 5 vs 3 candidates
   - Recommendation: Start with 3 per CONTEXT, make configurable

2. **Caching disambiguation decisions vs individual lookups**
   - What we know: 7-day cache TTL per CONTEXT, DiskCache in use
   - What's unclear: Should full disambiguation decisions be cached or just candidate info?
   - Recommendation: Cache both - candidate info for reuse, decisions for resume capability

3. **Review file format for power users**
   - What we know: CONTEXT specifies JSON review file with candidates, confidence, rationale
   - What's unclear: Exact fields power users need for effective review
   - Recommendation: Include full context, all candidates with summaries, make easily parseable

## Sources

### Primary (HIGH confidence)

- [Claude Structured Outputs Documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) - Beta feature for guaranteed JSON
- [MediaWiki API:Pageprops](https://www.mediawiki.org/wiki/API:Pageprops) - Disambiguation page detection
- [MediaWiki Extension:Disambiguator](https://www.mediawiki.org/wiki/Extension:Disambiguator) - Disambiguation page property
- [MediaWiki API:Search](https://www.mediawiki.org/wiki/API:Search) - Multiple search results with srlimit
- [MediaWiki API:Links](https://www.mediawiki.org/wiki/API:Links) - Extracting links from disambiguation pages
- [Wikipedia-API PyPI](https://pypi.org/project/Wikipedia-API/) - Page summaries, categories, validation

### Secondary (MEDIUM confidence)

- [LLM Confidence Scoring Research](https://nanonets.com/blog/how-to-tell-if-your-llm-is-hallucinating/) - Self-reported confidence patterns
- [Confidence Scores in LLM Outputs](https://medium.com/@vatvenger/confidence-unlocked-a-method-to-measure-certainty-in-llm-outputs-1d921a4ca43c) - Scoring methodology
- [MediaWiki API:Opensearch](https://www.mediawiki.org/wiki/API:Opensearch) - Alternative search API

### Tertiary (LOW confidence)

- Research papers on entity disambiguation - Academic context, patterns validated against production use

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Same stack as Phase 2, all libraries verified
- Architecture: HIGH - Patterns follow project conventions, Claude structured outputs well-documented
- Disambiguation detection: HIGH - MediaWiki API documented, pageprops behavior confirmed
- Pitfalls: MEDIUM - Based on research and API documentation, some edge cases may exist

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - stable APIs, Claude structured outputs in beta)

**Assumptions:**
- Anthropic API key available (ANTHROPIC_API_KEY) - same as Phase 2
- Internet connectivity for Wikipedia API
- enriched_entities.json from Phase 1 contains context field
- Video topic/title available from Phase 2 or extractable from SRT filename
