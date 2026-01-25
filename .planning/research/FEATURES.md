# Feature Landscape: Wikipedia Search Disambiguation

**Domain:** LLM-assisted Wikipedia search and disambiguation for entity image retrieval
**Researched:** 2026-01-25
**Confidence:** MEDIUM (based on Wikipedia API documentation, LLM prompt engineering patterns, and existing codebase analysis)

## Table Stakes

Features users expect. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Multi-query search strategy generation | Current naive name-only search fails frequently; need multiple search terms upfront | Medium | LLM generates 2-4 Wikipedia search queries from entity name + story context |
| Candidate result comparison | When multiple Wikipedia pages match, must pick contextually correct one | Medium | LLM compares page summaries against story context |
| Disambiguation page detection | Wikipedia returns disambiguation pages (e.g., "William Dawes (disambiguation)") that must be resolved | Low | Check for "(disambiguation)" in title or parse disambiguation page links |
| Search fallback chain | Try progressively simpler queries if first attempts fail | Low | Entity name → canonical name → name without qualifiers → name + subject |
| Result validation | Verify Wikipedia page exists and has images before accepting | Low | Check page exists, has infobox or images, not stub/redirect |

## Differentiators

Features that set product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Context-aware query expansion | Generate domain-specific search terms using story context (e.g., "William Dawes" + "Australian genocide" → query for "William Dawes + colonist + Australia") | Medium | LLM prompt: "Given entity X and context Y, generate 3 Wikipedia search queries prioritizing historical/geographic disambiguation" |
| Confidence scoring | Score each candidate result's relevance to context; skip if below threshold | Medium | LLM rates 0-10 how well candidate matches context; require ≥7 for auto-selection |
| Temporal disambiguation | When entity has time markers in context, prioritize Wikipedia results from that era | Medium | Extract year/era from transcript context, filter candidates by historical period |
| Geographic disambiguation | When location mentioned near entity, prioritize Wikipedia results from that region | Low-Medium | Extract location from nearby cues, boost candidates mentioning that place |
| Alias-aware search | Use canonical name + known aliases from entity extraction to try multiple searches | Low | Already have aliases from entity extraction; try canonical first, then aliases |
| Result explanation | Log which query succeeded and why, for debugging and validation | Low | Record: query used, candidates considered, selection rationale |

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Manual disambiguation UI | This is a CLI tool for batch processing; GUI breaks the workflow and requires user attention mid-run | Use confidence thresholds; log ambiguous cases to CSV for post-run review |
| Exhaustive Wikipedia search | Trying dozens of query variations or crawling disambiguation pages deeply wastes API quota and time | Cap at 3-5 search attempts per entity; mark as failed and move on |
| Image-first search | Searching for images before confirming correct Wikipedia page | Always confirm page first, then check images; wrong page = wrong images even if images exist |
| Perfect disambiguation | Trying to resolve 100% of entities correctly | Accept 80-90% success rate; log failures for manual review rather than over-engineering |
| Third-party disambiguation services | External services (DBpedia, Wikidata) add dependencies and complexity | Wikipedia API + LLM is sufficient; Wikidata is optional enrichment, not core |
| Interactive prompting | Asking user to choose between candidates mid-run | Breaks automation; use LLM to decide or mark as ambiguous |
| Over-specific queries | Adding too much context makes queries too narrow and miss valid pages | Balance specificity (2-3 context terms) vs. recall |

## Feature Dependencies

```
Wikipedia Search Flow:
1. Query Generation (table stakes) → must happen before search
2. Search Execution → returns candidates
3. Disambiguation Detection (table stakes) → identifies if disambiguation needed
4. Candidate Comparison (table stakes) → picks best match
5. Result Validation (table stakes) → confirms page usable
6. Confidence Scoring (differentiator) → gates auto-acceptance

Optional Enhancements (independent):
- Context-aware query expansion (improves step 1)
- Temporal/geographic disambiguation (improves step 4)
- Alias-aware search (adds retry to step 2)
- Result explanation (enriches logging throughout)

Dependencies:
- Query Generation requires: entity name, entity type, story context (transcript excerpt)
- Candidate Comparison requires: Wikipedia page summaries (first paragraph via API)
- Temporal/Geographic disambiguation requires: context extraction (year, location from nearby cues)
```

## Detailed Feature Specifications

### 1. Multi-Query Search Strategy Generation (Table Stakes)

**What:** LLM generates 2-4 Wikipedia search queries from entity name + story context.

**Why critical:** Naive search using only entity name fails when:
- Name is ambiguous (William Dawes: colonist vs. revolutionary)
- Name doesn't match Wikipedia title (Obama → Barack Obama)
- Entity needs qualifiers (Federal War → Federal War (Venezuela))

**Implementation approach:**

```python
# LLM prompt pattern:
system_prompt = """You generate Wikipedia search queries to find the correct article for a named entity.
Given an entity name and story context, return 2-4 search queries in order of specificity:
1. Most specific: entity + key disambiguating context
2. Canonical: full Wikipedia-style name
3. Simplified: entity name only
4. Fallback: entity + general domain

Return JSON array of strings. Example:
{"queries": ["William Dawes colonist Australia", "William Dawes (Australian)", "William Dawes", "William Dawes 18th century"]}
"""

user_prompt = f"""Entity: {entity_name}
Entity type: {entity_type}
Story context: {context_window}

Generate Wikipedia search queries."""
```

**API integration:**
- Use Wikipedia `action=opensearch` or `action=query&list=search` for each query
- Try queries in order until valid result found
- Cache results to avoid duplicate API calls

**Edge cases:**
- Entity already fully qualified → return as-is plus simplified version
- Very generic entity (e.g., "elections") → require context in all queries
- Entity is a year/date → append subject context

**Success criteria:**
- At least one query returns valid Wikipedia page
- Query order optimizes for precision first (fewer false positives)

### 2. Candidate Result Comparison (Table Stakes)

**What:** When multiple Wikipedia pages match search, LLM picks the contextually correct one.

**Why critical:** Search often returns multiple valid pages:
- Disambiguation pages with 5-20 options
- Similar names (Barack Obama, Barack Obama Sr.)
- Same person with multiple articles (main bio + specific events)

**Implementation approach:**

```python
# LLM prompt pattern:
system_prompt = """You select the correct Wikipedia article from multiple candidates.
Compare article summaries against the story context and return the best match.
Return JSON with selected article title and confidence (0-10).
If no good match, return confidence 0.

Example: {"title": "William Dawes (marine)", "confidence": 9, "rationale": "Context mentions Australian colonist and genocide; this article is about the Australian Marine officer involved in colonization"}
"""

user_prompt = f"""Entity: {entity_name}
Story context: {context_window}

Candidates:
{format_candidates_with_summaries(candidates)}

Select best match."""
```

**API integration:**
- Fetch first paragraph of each candidate via `action=query&prop=extracts&exintro=1`
- Limit to top 5 candidates to control token costs
- Use batch API calls where possible

**Scoring rubric (for LLM guidance):**
- 9-10: Perfect match (name, time, place all align)
- 7-8: Strong match (2/3 factors align)
- 5-6: Possible match (1/3 factors align)
- 0-4: Poor match (conflicts or irrelevant)

**Edge cases:**
- All candidates have low confidence → mark as ambiguous, log for review
- Multiple candidates with similar scores → pick highest, log alternatives
- Disambiguation page in candidates → parse and add specific options to candidate list

**Success criteria:**
- Select correct article 85%+ of time (measured by spot-checking)
- Confidence scores correlate with accuracy

### 3. Disambiguation Page Detection (Table Stakes)

**What:** Detect when Wikipedia returns a disambiguation page and extract actual article links.

**Why critical:** Wikipedia search often returns disambiguation pages as top result. These are not usable articles.

**Implementation approach:**

```python
def is_disambiguation_page(title: str, page_content: dict) -> bool:
    """Detect disambiguation pages via title or content markers."""
    if "(disambiguation)" in title.lower():
        return True

    # Check for disambiguation category
    categories = page_content.get("categories", [])
    if any("disambiguation" in cat.lower() for cat in categories):
        return True

    # Check for disambiguation template in HTML
    html = page_content.get("parse", {}).get("text", "")
    if 'class="mw-disambig"' in html or 'dmbox-disambig' in html:
        return True

    return False

def extract_disambiguation_links(page_html: str) -> List[str]:
    """Parse disambiguation page to extract article links."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page_html, "html.parser")

    # Disambiguation pages list articles in <ul> tags
    links = []
    for li in soup.select("ul li"):
        a = li.find("a", href=True)
        if a and a["href"].startswith("/wiki/"):
            title = a.get("title") or a.text.strip()
            if ":" not in title:  # Skip meta pages
                links.append(title)

    return links[:10]  # Limit to first 10 options
```

**API integration:**
- Check `action=query&prop=categories` for disambiguation category
- Parse HTML via `action=parse&prop=text` if needed
- Re-run candidate comparison with extracted links

**Edge cases:**
- Partial disambiguation (page exists but also links to others) → use main page
- No links extracted → fall back to next search query
- Circular disambiguation (A → B → A) → detect loop, fail gracefully

### 4. Context-Aware Query Expansion (Differentiator)

**What:** Generate domain-specific search terms using story context (time period, location, event type).

**Why valuable:** Simple context-free queries miss nuances. "William Dawes" + "genocide" + "Australia" → much better than just "William Dawes colonist".

**Implementation approach:**

```python
# Enhanced LLM prompt:
system_prompt = """You generate Wikipedia search queries using contextual clues.
Extract key disambiguating information from the story context:
- Time period (year, decade, century, era)
- Geographic location (country, region, city)
- Event type (war, revolution, political office, etc.)
- Related entities mentioned nearby

Incorporate these into search queries strategically:
- Most specific: entity + time + place + event type
- Time-based: entity + time period
- Place-based: entity + location
- Canonical: full name only

Return JSON array of queries ordered by specificity."""

user_prompt = f"""Entity: {entity_name} ({entity_type})
Story context (5 sentences around mention):
{expanded_context}

Related entities nearby: {nearby_entities}

Generate Wikipedia search queries."""
```

**Context extraction helpers:**

```python
def extract_temporal_context(cue_text: str, nearby_cues: List[str]) -> Optional[str]:
    """Extract year, decade, or era from context."""
    # Look for explicit years
    year_match = re.search(r'\b(1\d{3}|20\d{2})\b', cue_text)
    if year_match:
        return year_match.group(1)

    # Look for era markers
    era_patterns = [
        r'(\d{2}th century)',
        r'(pre-colonial|colonial|post-colonial)',
        r'(ancient|medieval|modern|contemporary)',
        r'(early|mid|late) (\d{4}s)',
    ]
    for pattern in era_patterns:
        match = re.search(pattern, cue_text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None

def extract_geographic_context(cue_text: str, entities_map: dict) -> Optional[str]:
    """Extract location from context or nearby place entities."""
    # Check nearby place entities
    # (Already extracted by srt_entities.py)

    # Look for location keywords
    location_match = re.search(r'\b(in|from|at|near)\s+([A-Z][a-zA-Z\s]+)', cue_text)
    if location_match:
        return location_match.group(2).strip()

    return None
```

**Success criteria:**
- Context-enhanced queries find correct page when simple queries fail
- Reduce ambiguous results by 30%+

### 5. Confidence Scoring (Differentiator)

**What:** LLM rates each candidate result's relevance to context on 0-10 scale; require ≥7 for auto-selection.

**Why valuable:** Prevents false positives. Better to skip an entity than download wrong images.

**Implementation approach:**

```python
CONFIDENCE_THRESHOLD = 7  # Configurable

def select_candidate_with_confidence(
    entity_name: str,
    context: str,
    candidates: List[dict]
) -> Optional[dict]:
    """Select best candidate only if confidence meets threshold."""

    result = llm_compare_candidates(entity_name, context, candidates)

    confidence = result.get("confidence", 0)
    selected_title = result.get("title")
    rationale = result.get("rationale", "")

    if confidence >= CONFIDENCE_THRESHOLD:
        return {
            "title": selected_title,
            "confidence": confidence,
            "rationale": rationale,
            "status": "auto_selected"
        }
    elif confidence >= 4:
        # Uncertain match - log for review
        return {
            "title": selected_title,
            "confidence": confidence,
            "rationale": rationale,
            "status": "needs_review"
        }
    else:
        # No good match
        return {
            "title": None,
            "confidence": 0,
            "rationale": "No confident match found",
            "status": "failed"
        }
```

**Logging strategy:**

```python
# Write to DISAMBIGUATION_LOG.csv
fieldnames = [
    "entity_name",
    "entity_type",
    "query_used",
    "candidates_count",
    "selected_title",
    "confidence",
    "status",  # auto_selected, needs_review, failed
    "rationale",
    "timecode"
]
```

**Edge cases:**
- Multiple high-confidence candidates → pick highest, log alternatives
- Confidence threshold too high → tune down if >20% failure rate
- LLM returns invalid confidence → default to 0, log error

**Success criteria:**
- Auto-selected results (≥7 confidence) have 95%+ accuracy
- Needs-review results (4-6 confidence) have 70%+ accuracy
- Failed results (<4 confidence) correctly reject bad matches

### 6. Alias-Aware Search (Differentiator)

**What:** Use canonical name + known aliases from entity extraction to try multiple searches.

**Why valuable:** Entity extraction already identifies aliases (Obama → Barack Obama). Searching with aliases improves recall.

**Implementation approach:**

```python
def generate_search_queries_with_aliases(
    canonical_name: str,
    aliases: List[str],
    entity_type: str,
    context: str
) -> List[str]:
    """Generate queries using canonical name and aliases."""

    # Start with canonical (most likely to match Wikipedia title)
    queries = [canonical_name]

    # Add context-enhanced canonical
    context_query = generate_context_query(canonical_name, context)
    if context_query != canonical_name:
        queries.append(context_query)

    # Try aliases (often surface forms from transcript)
    for alias in aliases[:3]:  # Limit to top 3 aliases
        if alias != canonical_name:
            queries.append(alias)
            # Also try alias + context
            alias_context = generate_context_query(alias, context)
            if alias_context not in queries:
                queries.append(alias_context)

    # Deduplicate while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique_queries.append(q)

    return unique_queries[:5]  # Cap at 5 total queries
```

**Integration with existing code:**

```python
# From entities_map.json:
entity_data = {
    "Barack Obama": {
        "entity_type": "people",
        "aliases": ["Obama", "President Obama", "Barack"],
        "occurrences": [...]
    }
}

# Use aliases in search:
canonical = "Barack Obama"
aliases = entity_data["aliases"]
queries = generate_search_queries_with_aliases(
    canonical, aliases, "people", context
)
```

**Success criteria:**
- Alias queries succeed when canonical name fails
- Cover 10-15% additional entities vs. canonical-only search

### 7. Result Explanation (Differentiator)

**What:** Log which query succeeded, candidates considered, and selection rationale.

**Why valuable:** Debugging failed searches, validating LLM decisions, building dataset for future improvements.

**Implementation approach:**

```python
# Enhanced logging structure
class DisambiguationResult:
    entity_name: str
    entity_type: str
    queries_tried: List[str]
    query_succeeded: Optional[str]
    candidates_found: List[dict]  # title, summary, score
    selected_title: Optional[str]
    confidence: float
    rationale: str
    status: str  # success, needs_review, failed
    error: Optional[str]

    def to_log_entry(self) -> dict:
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "queries_tried": " | ".join(self.queries_tried),
            "query_succeeded": self.query_succeeded or "NONE",
            "candidates_count": len(self.candidates_found),
            "candidates_titles": " | ".join([c["title"] for c in self.candidates_found[:5]]),
            "selected_title": self.selected_title or "NONE",
            "confidence": self.confidence,
            "status": self.status,
            "rationale": self.rationale,
            "error": self.error or ""
        }

# Write to detailed log CSV
def log_disambiguation_result(result: DisambiguationResult, log_path: Path):
    """Append disambiguation result to log."""
    fieldnames = [
        "entity_name", "entity_type", "queries_tried", "query_succeeded",
        "candidates_count", "candidates_titles", "selected_title",
        "confidence", "status", "rationale", "error"
    ]
    # Append to CSV...
```

**Log analysis helpers:**

```python
def analyze_disambiguation_log(log_path: Path) -> dict:
    """Analyze disambiguation log for success metrics."""
    import pandas as pd
    df = pd.read_csv(log_path)

    return {
        "total_entities": len(df),
        "auto_selected": len(df[df.status == "auto_selected"]),
        "needs_review": len(df[df.status == "needs_review"]),
        "failed": len(df[df.status == "failed"]),
        "avg_confidence": df[df.confidence > 0].confidence.mean(),
        "most_common_failures": df[df.status == "failed"].entity_type.value_counts().to_dict(),
        "query_success_rate": len(df[df.query_succeeded != "NONE"]) / len(df)
    }
```

**Success criteria:**
- Log enables debugging 100% of failures
- Rationale text explains LLM decision clearly
- Log dataset supports future model fine-tuning

## MVP Recommendation

For MVP, prioritize core disambiguation flow:

1. **Multi-query search strategy generation** (table stakes) - Foundation for all disambiguation
2. **Candidate result comparison** (table stakes) - Core decision logic
3. **Disambiguation page detection** (table stakes) - Handles common Wikipedia pattern
4. **Result validation** (table stakes) - Prevents bad downloads
5. **Confidence scoring** (differentiator) - Gates quality, reduces false positives
6. **Result explanation** (differentiator) - Debugging and validation

Defer to post-MVP:

- **Context-aware query expansion** - Nice optimization but query generation covers basics
- **Temporal/geographic disambiguation** - Specialized improvement, context comparison handles this implicitly
- **Alias-aware search** - Incremental improvement, can add as retry fallback later

## Implementation Notes

### Wikipedia API Considerations

**Rate limiting:**
- Current code uses 0.1s delay; Wikipedia allows ~200 req/min for registered users
- User-Agent identifies bot → may get better rate limits if registered
- No paid Wikipedia API tier exists; must respect community limits

**API methods for disambiguation:**

```python
# 1. Search for candidates (opensearch is faster but less info)
params = {
    "action": "opensearch",
    "search": query,
    "limit": 5,
    "namespace": 0,  # Main articles only
    "format": "json"
}

# 2. Get page summaries for comparison (query is more flexible)
params = {
    "action": "query",
    "titles": "|".join(candidate_titles),
    "prop": "extracts|categories",
    "exintro": 1,  # First paragraph only
    "explaintext": 1,  # Plain text, no HTML
    "format": "json"
}

# 3. Check disambiguation status
params = {
    "action": "query",
    "titles": page_title,
    "prop": "categories",
    "cllimit": 100,
    "format": "json"
}
```

**Batch API optimization:**
- Fetch summaries for all candidates in single call (up to 50 titles)
- Reduces API calls from N to 1 for N candidates

### LLM Prompt Engineering

**Token efficiency:**
- Use structured prompts with clear output format (JSON)
- Limit context window to 5 sentences around entity mention (~200 tokens)
- Batch candidate comparison (pass all 5 candidates in one LLM call vs. 5 separate calls)

**Prompt patterns:**

```python
# Query generation: ~300 tokens in + ~100 tokens out
# Candidate comparison: ~800 tokens in + ~150 tokens out
# Total per entity: ~450 tokens (~$0.0002 with GPT-4o-mini)

# For 100 entities:
# - 100 query generations: 40K tokens
# - 80 candidate comparisons (20 are direct hits): 76K tokens
# - Total: ~116K tokens (~$0.05 with GPT-4o-mini)
```

**Model selection:**
- GPT-4o-mini: Fast, cheap, good enough for structured tasks
- GPT-4o: Better at nuanced disambiguation but 10x cost
- Ollama (llama3): Free but slower, requires local GPU

### Edge Case Handling

**Known problematic patterns:**

| Pattern | Example | Solution |
|---------|---------|----------|
| Common surname | "Smith", "Jones" | Require context in all queries; fail if confidence <7 |
| Year-only entity | "1947" | Append subject context ("1947 Venezuela") |
| Generic event | "elections" | Require place qualifier in canonical name |
| Same person, multiple articles | "Barack Obama" vs "Presidency of Barack Obama" | Prefer biography article (shorter title, has "(person)" in categories) |
| Non-English names | "José Antonio Páez" | Preserve Unicode, try simplified version as fallback |
| Nicknames/titles | "The Liberator" | Try expanding to full name via LLM first |
| Living vs historical person | "William Dawes" (2 people, different centuries) | Use temporal context heavily in comparison |

**Failure modes:**

| Failure | Frequency | Mitigation |
|---------|-----------|-----------|
| No Wikipedia page exists | ~15% | Mark as failed, log for manual sourcing |
| Multiple equally valid matches | ~5% | Pick highest confidence, log alternatives for review |
| Wrong page selected | ~10% | Confidence threshold + manual review catches most |
| Wikipedia API timeout | ~1% | Retry with exponential backoff (existing code has this) |
| LLM returns invalid JSON | ~2% | Regex parse or fallback to default logic |

## Testing Strategy

**Unit tests:**
- Disambiguation page detection (sample HTML)
- Query generation (entity + context → expected queries)
- Confidence threshold gating (scores → status)

**Integration tests:**
- Search → candidates → comparison → selection (full flow)
- Known ambiguous entities (William Dawes, John Smith, etc.)
- Edge cases (year-only, generic events, common surnames)

**Manual validation dataset:**
- 50 entities from actual transcript
- Human labels for correct Wikipedia page
- Measure: precision, recall, confidence calibration

**Success metrics:**
- Precision: 85%+ (selected pages are correct)
- Recall: 80%+ (find page when it exists)
- Confidence calibration: high-confidence (≥7) → 95%+ accuracy

## Research Confidence

| Area | Confidence | Notes |
|------|------------|-------|
| Wikipedia API patterns | HIGH | Well-documented, stable API; existing code uses it successfully |
| LLM prompt patterns | HIGH | Structured extraction and comparison are established patterns |
| Disambiguation techniques | MEDIUM | Approaches are sound but need validation with real data |
| Edge case coverage | MEDIUM | List is comprehensive but new edge cases will emerge |
| Performance/cost | MEDIUM | Token estimates are rough; need real usage data |

## Sources

**Wikipedia API:**
- Wikipedia API Documentation: https://www.mediawiki.org/wiki/API:Main_page (official)
- Search API: https://www.mediawiki.org/wiki/API:Search (official)
- Page extracts: https://www.mediawiki.org/wiki/Extension:TextExtracts (official)

**LLM Prompt Engineering:**
- Structured output prompts: Common pattern in OpenAI documentation
- Entity disambiguation: Standard NLP task, well-studied in literature

**Existing Codebase:**
- wikipedia_image_downloader.py: Implements Wikipedia search (line 60), metadata query (line 529), disambiguation handling (partial)
- srt_entities.py: LLM entity extraction with canonical name resolution (lines 146-215), alias handling (lines 217-234)
- download_entities.py: Parallel download coordination, already uses entity type for prioritization (line 162)

**Confidence Notes:**
- HIGH confidence on Wikipedia API usage patterns (existing code proves viability)
- MEDIUM confidence on disambiguation success rates (need empirical validation)
- LOW confidence on cost estimates (token usage depends on context window size)

## Open Questions

1. **How much context is optimal?** 5 sentences? 10? Entire cue? Adjacent cues?
   - Needs A/B testing with real transcripts

2. **Should we use Wikidata for disambiguation?** Wikidata has canonical entity IDs that could help.
   - Adds complexity (new API) but might improve accuracy
   - Defer to post-MVP unless Wikipedia-only approach shows <70% success

3. **How to handle entities with no Wikipedia page?** (~15% of entities)
   - Current approach: mark as failed, log for manual sourcing
   - Alternative: fall back to Wikimedia Commons direct search (images without articles)

4. **Should disambiguation be entity-type aware?** People vs places vs events may need different strategies.
   - People: prefer biographical articles, use lifespan for temporal matching
   - Places: prefer main place article over historical events at that place
   - Events: require strong temporal/geographic context
   - This likely improves accuracy; consider for phase 2

5. **How to measure disambiguation quality in production?** Need feedback loop.
   - Manual spot-checking (sample 20 entities per run)
   - User feedback mechanism (mark incorrect images)
   - Build validation dataset over time for automated testing
