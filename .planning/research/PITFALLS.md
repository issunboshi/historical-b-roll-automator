# Domain Pitfalls: Wikipedia API + LLM Disambiguation

**Domain:** Wikipedia image download with LLM-based search strategy and disambiguation
**Researched:** 2026-01-25
**Confidence:** HIGH (based on codebase analysis + Wikipedia API documented behavior)

## Critical Pitfalls

Mistakes that cause rewrites, bans, or major system failures.

### Pitfall 1: Missing or Generic User-Agent → Immediate Ban

**What goes wrong:** Wikipedia API returns 403 Forbidden or silently rate-limits requests to oblivion.

**Why it happens:** MediaWiki API servers actively block requests with:
- No User-Agent header
- Generic User-Agent (Python-requests, curl, wget)
- User-Agent without contact information

**Consequences:**
- Immediate 403 errors on all requests
- Silent rate limiting (requests succeed but extremely slow)
- IP-level ban requiring manual unblock request

**Prevention:**
```python
# GOOD
User-Agent: MyBRollTool/1.0 (https://github.com/user/repo; user@email.com)

# BAD
User-Agent: Python-requests/2.31.0
User-Agent: Mozilla/5.0  # pretending to be a browser
(no User-Agent)  # missing entirely
```

**Current codebase status:** GOOD - uses custom User-Agent with project name (line 35)

**Detection:** Watch for 403 errors or sudden slowdowns without 429 responses

**Phase impact:** Must validate before Phase 1 (higher throughput) - getting banned blocks all work

---

### Pitfall 2: LLM Hallucinating Non-Existent Wikipedia Titles

**What goes wrong:** LLM generates plausible but non-existent Wikipedia article names. Your code tries to fetch them, gets no results, and silently fails to find images for valid entities.

**Why it happens:**
- LLMs are trained on Wikipedia text, not the current index
- LLMs confuse article titles with redirects (e.g., "Obama" exists but redirects to "Barack Obama")
- LLMs generate titles that sound right but never existed
- Article deletions/merges post-training

**Consequences:**
- Silent failures (entity extraction succeeds, image download finds nothing)
- No error logged because API call succeeds but returns empty results
- User never realizes the LLM sent you to the wrong article

**Prevention:**

1. **Always verify titles exist before download:**
```python
# After LLM suggests "William Dawes (patriot)"
params = {
    "action": "query",
    "titles": suggested_title,
    "format": "json"
}
# Check if page.missing is present → article doesn't exist
```

2. **Use search API as fallback:**
```python
# If exact title fails, try search
params = {
    "action": "query",
    "list": "search",
    "srsearch": entity_name,
    "srlimit": 5  # get alternatives for disambiguation
}
```

3. **Log hallucinations for LLM fine-tuning:**
```python
if page.get("missing"):
    log_hallucination(entity_name, llm_suggested_title, context)
```

**Detection:**
- Entity has images in Wikipedia but your tool finds none
- DOWNLOAD_SUMMARY.tsv shows 0 results for known entities
- Spike in "No Wikipedia results found" without corresponding spike in genuinely obscure entities

**Phase impact:** Phase 2 (LLM search strategy) - must validate suggestions before API calls

---

### Pitfall 3: Disambiguation Page Infinite Loop

**What goes wrong:** LLM picks "William Dawes" → Wikipedia returns disambiguation page → LLM picks another disambiguation page → loop continues until rate limit or timeout.

**Why it happens:**
- Disambiguation pages link to other disambiguation pages (e.g., "William Dawes" → "William Dawes (disambiguation)" → "Dawes (surname)")
- Current code only checks top search result (line 60-81)
- No detection that page is a disambiguation page vs actual article

**Consequences:**
- Wasted API calls (each disambiguation check burns rate limit)
- Wasted LLM calls (each disambiguation attempt costs money)
- Download finds no images (disambiguation pages have no infobox images)
- Silent failure (no error, just empty results)

**Prevention:**

1. **Detect disambiguation pages:**
```python
# Method 1: Check categories
params = {
    "action": "query",
    "prop": "categories",
    "titles": page_title,
    "cllimit": 50
}
# Look for "Category:Disambiguation pages" or "Category:All disambiguation pages"

# Method 2: Check page content for disambiguation template
params = {
    "action": "query",
    "prop": "templates",
    "titles": page_title,
    "tllimit": 50
}
# Look for "Template:Disambiguation" or "Template:Disambig"
```

2. **Set maximum disambiguation depth:**
```python
MAX_DISAMBIGUATION_ATTEMPTS = 3
if disambiguation_attempts >= MAX_DISAMBIGUATION_ATTEMPTS:
    raise TooManyDisambiguationPages(entity_name)
```

3. **Cache disambiguation results:**
```python
# Don't ask LLM about same entity twice
disambiguation_cache[entity_name] = chosen_title
```

**Detection:**
- API call count spikes relative to entity count (>3 calls per entity)
- Long processing times with no downloaded images
- FAILED_DOWNLOADS.csv shows repeated attempts for same entity

**Current codebase status:** VULNERABLE - search_wikipedia_page() returns first result without disambiguation check

**Phase impact:** Phase 2 (LLM disambiguation) - must implement before production use

---

### Pitfall 4: Rate Limit Ignorance → IP Ban

**What goes wrong:** You ignore 429 (Too Many Requests) responses or don't implement exponential backoff. Wikipedia escalates from soft throttling to hard IP ban.

**Why it happens:**
- Current code has retry logic (line 769-798) but may retry too aggressively
- No monitoring of rate limit warnings before 429
- Wikipedia uses `maxlag` parameter (line 72, 96, etc.) but doesn't always respect it
- Parallel execution without shared rate limiter

**Consequences:**
- Temporary IP ban (hours to days)
- Permanent IP ban if repeated violations
- All users from same IP blocked (bad for shared hosting/CI)

**Prevention:**

1. **Respect Retry-After header (current code DOES this correctly - line 775-783):**
```python
if resp.status_code == 429:
    retry_after = resp.headers.get("Retry-After")
    # Current code correctly parses and sleeps
```

2. **Monitor maxlag warnings:**
```python
data = resp.json()
if "error" in data and data["error"]["code"] == "maxlag":
    # Database replica is lagging; must back off
    lag_seconds = data["error"]["lag"]
    sleep(lag_seconds + buffer)
```

3. **Global rate limiter for parallel downloads:**
```python
# BAD: Each worker has own delay (current implementation)
# download_entities.py line 252: delay per subprocess

# GOOD: Shared semaphore across workers
from threading import Semaphore
rate_limit_semaphore = Semaphore(1)
```

**Detection:**
- 429 errors in logs
- `maxlag` errors in API responses
- Sudden drop in successful downloads
- Increasing response times without 429

**Current codebase status:** PARTIAL - good retry logic, but parallel execution (download_entities.py -j flag) doesn't share rate limiter

**Phase impact:** Phase 1 (higher throughput) - MUST fix before enabling parallel downloads

---

### Pitfall 5: LLM Disambiguation Bias → Wrong Person Every Time

**What goes wrong:** LLM consistently picks the more famous person regardless of transcript context.

Example: Transcript discusses Australian colonial history. Entity: "William Dawes". LLM always picks William Dawes (patriot) because American Revolution is more prominent in training data.

**Why it happens:**
- LLM training data has recency/popularity bias
- Prompt doesn't emphasize context matching over fame
- No validation that chosen article matches context

**Consequences:**
- Images show wrong person (American patriot instead of Australian colonist)
- User loses trust in automation
- Must manually review every ambiguous entity
- Defeats purpose of LLM disambiguation

**Prevention:**

1. **Context-heavy prompts:**
```python
# BAD
"Which William Dawes does this refer to: 1) patriot 2) astronomer?"

# GOOD
"Given this transcript about Australian colonial history, which William Dawes
is more likely:
1) William Dawes (1762-1836) - Australian colonist and astronomer
2) William Dawes (1745-1799) - American patriot

Transcript context: {surrounding_sentences}"
```

2. **Require explicit reasoning:**
```python
{
  "chosen_article": "William Dawes (colonist)",
  "reasoning": "Transcript mentions Sydney Cove and Australian colony",
  "confidence": "high"
}
```

3. **Validate with image metadata:**
```python
# After downloading, check image descriptions
if "American" in image_description and "Australian" in transcript_context:
    flag_mismatch(entity_name)
```

**Detection:**
- User reports wrong images
- Image descriptions don't match transcript context
- Audit random sample: do images match story?

**Phase impact:** Phase 2 (LLM disambiguation) - test on ambiguous entities before shipping

---

### Pitfall 6: Cost Explosion from Redundant LLM Calls

**What goes wrong:** LLM called for every entity mention, even duplicates. 100 mentions of "Obama" = 100 LLM calls.

**Why it happens:**
- Entity extraction happens per cue (srt_entities.py line 48+)
- No deduplication before disambiguation
- No caching of previous disambiguation decisions

**Consequences:**
- LLM costs scale with transcript length, not entity uniqueness
- Long transcripts with repeated names = bankruptcy
- Slow processing (LLM latency on critical path)

**Prevention:**

1. **Deduplicate before disambiguation:**
```python
# Current code does this! (entities_map.json structure)
unique_entities = set(all_mentions)
for entity in unique_entities:
    disambiguate_once(entity)
```

2. **Cache disambiguation results:**
```python
# Per-run cache
disambiguation_cache = {}

# Persistent cache across runs
# .cache/disambiguation.json
{
  "William Dawes + Australian colonial history": "William Dawes (colonist)"
}
```

3. **Batch LLM calls:**
```python
# Instead of 1 call per entity
disambiguate_batch([
  {"entity": "Obama", "context": "..."},
  {"entity": "Biden", "context": "..."},
  # ...
])
```

**Detection:**
- LLM cost scales linearly with transcript duration
- API logs show repeated identical disambiguation requests
- Processing time dominated by LLM calls

**Current codebase status:** GOOD - entities_map.json deduplicates (download_entities.py processes unique entities)

**Phase impact:** Phase 2 (LLM disambiguation) - implement caching from day 1

---

## Moderate Pitfalls

Mistakes that cause delays or technical debt.

### Pitfall 7: Ignoring Wikipedia Redirects

**What goes wrong:** LLM suggests "Obama" but Wikipedia API returns redirect to "Barack Obama". Your code doesn't follow redirects and fails.

**Why it happens:**
- Wikipedia has thousands of redirects (common names → full names)
- API parameter `redirects=1` not set (current code DOES set it - line 545)

**Prevention:**
- Always use `redirects=1` in API calls (current code correct)
- Handle normalized titles: API returns both redirect source and target

**Current codebase status:** GOOD - uses redirects=1

---

### Pitfall 8: Search vs Get Confusion

**What goes wrong:** Using `action=query&list=search` when you have exact title, or using `action=query&titles=` when title is ambiguous.

**Why it happens:**
- Search is fuzzy, slow, and returns snippets
- Get is exact, fast, but requires precise title

**Prevention:**
```python
# Use search when: LLM provides entity concept, not exact title
search_wikipedia_page(session, "william dawes")

# Use get when: LLM provides exact Wikipedia title
get_wikipedia_page(session, "William Dawes (colonist)")
```

**Current codebase status:** Uses search (correct for current workflow)

**Phase impact:** Phase 2 - may switch to get if LLM provides exact titles

---

### Pitfall 9: Image Metadata Parsing Failures

**What goes wrong:** Wikipedia extmetadata has nested HTML, inconsistent fields, missing data. Naive parsing breaks.

**Why it happens:**
- Metadata values are HTML, not plain text
- Fields are optional (author, license, date may be missing)
- Structure varies by file age and source

**Prevention:**
- Current code uses BeautifulSoup to strip HTML (line 364-370) - GOOD
- Graceful defaults for missing fields (line 580-586) - GOOD

**Current codebase status:** GOOD - handles this correctly

---

### Pitfall 10: Parallel Download Race Conditions

**What goes wrong:** Two workers download same entity simultaneously, corrupt files or attribution data.

**Why it happens:**
- download_entities.py supports `-j` parallel flag (line 253)
- No file-level locking
- Directory existence check isn't atomic (line 137)

**Prevention:**
```python
# Current mitigation: check if entity_dir exists (line 137)
if entity_dir.exists():
    skip

# Better: Use file locks
import fcntl
with open(lock_file, 'w') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    # download entity
```

**Detection:**
- Corrupted DOWNLOAD_SUMMARY.tsv (interleaved writes)
- Missing images despite successful download log

**Current codebase status:** PARTIAL - directory check helps but not foolproof

**Phase impact:** Phase 1 (higher throughput with parallelization) - test thoroughly

---

## Minor Pitfalls

Mistakes that cause annoyance but are fixable.

### Pitfall 11: SVG Symbolic Images (Flags, Signatures)

**What goes wrong:** Download flags, coats of arms, signatures instead of photos.

**Why it happens:** These are often the first images on Wikipedia pages for people/places.

**Prevention:**
- Current code filters symbolic SVGs (line 248-280) - GOOD
- Heuristic: check for "flag", "coat of arms", "signature" in filename/description

**Current codebase status:** GOOD - already implemented

---

### Pitfall 12: Disambiguation Page Has No Images

**What goes wrong:** Successfully "download" from disambiguation page, get 0 images, no error logged.

**Why it happens:** Disambiguation pages exist and return 200 OK, but have no content images.

**Prevention:** Detect disambiguation pages (see Pitfall 3)

**Current codebase status:** VULNERABLE - no disambiguation detection

---

### Pitfall 13: Image Year Inference Fragility

**What goes wrong:** Code infers image year from metadata/filename (line 297-319). False positives: "2020 Summer Olympics" image tagged as 2020, but it's historical.

**Why it happens:** Regex matches any 4-digit year pattern

**Prevention:**
- Use DateTimeOriginal first (camera EXIF), not description text
- Current code prioritizes EXIF (line 302-306) - GOOD

**Current codebase status:** GOOD - reasonable heuristic

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Higher throughput | Rate limit ban from parallelization (Pitfall 4) | Implement shared rate limiter; test with Wikipedia's test server first |
| Phase 1: Higher throughput | Parallel race conditions (Pitfall 10) | Use file locking or atomic directory creation |
| Phase 2: LLM search strategy | Hallucinated titles (Pitfall 2) | Validate all LLM suggestions against Wikipedia API before download |
| Phase 2: LLM search strategy | Cost explosion (Pitfall 6) | Cache disambiguation results; batch LLM calls |
| Phase 2: LLM disambiguation | Disambiguation loops (Pitfall 3) | Detect disambiguation pages; set max depth |
| Phase 2: LLM disambiguation | Fame bias (Pitfall 5) | Context-heavy prompts; require reasoning output |
| Phase 3: Image variety | Re-downloading same images | Track which images used for which mentions; download extra on first pass |

---

## Research Confidence Assessment

| Pitfall Category | Confidence | Source |
|------------------|------------|--------|
| Wikipedia API etiquette (1, 4) | HIGH | MediaWiki API documentation patterns + codebase analysis |
| LLM hallucination (2, 5, 6) | HIGH | Known LLM behavior patterns + domain knowledge |
| Disambiguation handling (3, 12) | HIGH | Wikipedia API structure + codebase gap analysis |
| Parallel execution (10) | MEDIUM | Codebase analysis; not tested under high concurrency |
| Image metadata parsing (9, 11, 13) | HIGH | Codebase implements correctly; well-understood domain |

---

## Summary: Top 3 Critical Risks

1. **Rate limiting → IP ban** (Pitfall 4): Current parallel implementation lacks shared rate limiter. MUST fix before Phase 1.

2. **LLM hallucination → silent failures** (Pitfall 2): No validation that LLM-suggested titles exist. MUST validate in Phase 2.

3. **Disambiguation loops → cost explosion** (Pitfall 3): No disambiguation page detection. MUST implement before Phase 2 production.

**Recommended roadmap adjustment:**
- Phase 0 (pre-Phase 1): Add shared rate limiter for parallel downloads
- Phase 2 must include: disambiguation detection, title validation, and result caching
- Phase 2 testing must include: ambiguous entities (William Dawes test case), non-existent LLM suggestions, disambiguation page loops
