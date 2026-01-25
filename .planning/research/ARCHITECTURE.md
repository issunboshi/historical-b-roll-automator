# Architecture Patterns: LLM-Based Search & Disambiguation Integration

**Domain:** B-roll automation pipeline with Wikipedia image download
**Researched:** 2026-01-25
**Confidence:** HIGH (based on existing codebase analysis and established pipeline patterns)

## Executive Summary

The existing three-stage pipeline (extract → download → timeline) should evolve into a four-stage pipeline with an intermediate enrichment stage. The key insight: **LLM operations should augment entity metadata early, not block download operations**. This allows the downloader to iterate through multiple search strategies and pick the best match, while maintaining the pipeline's fail-fast semantics and resume-from-checkpoint design.

**Recommended architecture:** Insert a new "enrich" stage between extraction and download that generates search strategies and accumulates transcript context. The download stage then consumes this enriched metadata, attempts searches, and uses LLM for disambiguation only when needed.

## Current Architecture (Baseline)

### Three-Stage Pipeline

```
Stage 1: Extract (tools/srt_entities.py)
  Input:  SRT transcript
  Process: LLM call per cue → entity extraction → canonical resolution
  Output: entities_map.json with:
    {
      "Barack Obama": {
        "entity_type": "people",
        "occurrences": [{timecode, cue_idx}],
        "images": [],
        "aliases": ["Obama", "Barack Obama"]
      }
    }

Stage 2: Download (tools/download_entities.py + wikipedia_image_downloader.py)
  Input:  entities_map.json
  Process: For each entity → Wikipedia search (exact name) → download first N images
  Output: entities_map.json updated with:
    "images": [{path, license, source_url}]

Stage 3: Timeline (generate_broll_xml.py)
  Input:  entities_map.json (with images)
  Process: Round-robin image assignment → track placement → FCP XML generation
  Output: broll_timeline.xml
```

### Current Data Flow Characteristics

- **Checkpoint-based**: entities_map.json persists state between stages
- **Subprocess isolation**: Each stage spawned independently; no shared memory
- **Parallel downloads**: Stage 2 uses ThreadPoolExecutor (4 workers default)
- **Fail-fast**: Pipeline stops on first subprocess failure
- **Idempotent-friendly**: Stages can re-run if output already exists

### Current Limitations

1. **Naive search**: Uses entity canonical name directly as Wikipedia search query
2. **No context**: Downloader has no access to transcript text for disambiguation
3. **First-match bias**: Takes first Wikipedia search result, which may be wrong
4. **No prioritization**: Downloads images for all entities equally (people, places, concepts, events)

## Proposed Architecture: Four-Stage Pipeline with Enrichment

### Overview

Insert a new Stage 1.5 "Enrich" between Extract and Download:

```
Stage 1: Extract
  ↓
  entities_map.json (basic)
  ↓
Stage 1.5: Enrich ← NEW
  ↓
  entities_map.json (enriched)
  ↓
Stage 2: Download
  ↓
  entities_map.json (with images)
  ↓
Stage 3: Timeline
```

### Stage 1.5: Enrich (tools/enrich_entities.py)

**Purpose:** Augment entity metadata with LLM-generated search strategies and contextual information BEFORE download attempts.

**Input:**
- entities_map.json (from extraction)
- Original SRT transcript (for context gathering)

**Process:**

1. **Priority scoring** (deterministic, no LLM needed)
   - Assign priority: people=1.0, events=0.9, concepts=0.6, places=0.3
   - Sort entities by: priority DESC, occurrence_count DESC

2. **Context gathering** (per entity)
   - For each occurrence, extract ±N words of context from transcript
   - Store consolidated context window (e.g., 100 words max)

3. **Search strategy generation** (LLM call per entity)
   - Prompt: "Given entity '{canonical}' mentioned in context: '{context}', suggest 3 Wikipedia search queries, ordered by likelihood of finding the correct article."
   - LLM returns: `["query1", "query2", "query3"]`
   - Store in entity metadata: `"search_strategies": [...]`

4. **Subject resolution** (one LLM call total, or reuse from extraction)
   - Determine overall transcript subject (e.g., "Venezuelan history")
   - Store in root of entities_map.json: `"subject": "Venezuela"`

**Output structure:**

```json
{
  "subject": "Venezuela",
  "entities": {
    "William Dawes": {
      "entity_type": "people",
      "priority": 1.0,
      "occurrences": [...],
      "context": "...mentioned William Dawes arrived in Sydney Cove...",
      "search_strategies": [
        "William Dawes (surveyor)",
        "William Dawes Australia colonist",
        "William Dawes Sydney"
      ],
      "images": []
    }
  }
}
```

**LLM Usage:**
- One call per entity (~50-200 entities typical)
- Batch-friendly: Can parallelize or use async if API supports
- Cost-efficient: Small prompts (~200 tokens), short responses (~50 tokens)

**Exit conditions:**
- Skip enrichment if `search_strategies` already present (idempotent)
- Continue even if some LLM calls fail (log warning, use fallback: `[canonical_name]`)

### Stage 2: Download (Enhanced)

**New behavior:** Consume enriched metadata; attempt multiple searches; disambiguate when needed.

**Process per entity:**

1. **Priority filtering**
   - Skip low-priority entities based on rules:
     - Places: Only download if entity appears in first 10% of transcript OR mentioned 3+ times
     - Concepts: Only if mentioned 2+ times AND no better alternative
   - Reasoning: Avoid cluttering timeline with repetitive place images

2. **Multi-strategy search**
   - Iterate through `search_strategies` list in order
   - For each strategy:
     - Query Wikipedia API
     - Get top 3 results (not just 1)
     - If only 1 result: proceed with it (high confidence)
     - If 2+ results: disambiguation needed → call LLM

3. **Disambiguation** (LLM call, conditional)
   - Prompt: "Entity '{canonical}' mentioned in context: '{context}'. Which Wikipedia article is correct? Options: [list article titles/snippets]. Return the best match title."
   - LLM returns: Title of best match
   - Use that article for image download
   - Record decision in entity metadata: `"disambiguation": {"chosen": "...", "rejected": [...]}`

4. **Image download** (existing logic, unchanged)
   - Once article determined, download N images
   - Classify by license, store metadata

5. **Match quality tracking**
   - Record in entity: `"match_quality": "high" | "medium" | "low" | "none"`
   - High: Single search result or LLM-confirmed
   - Medium: Multiple strategies tried, images found
   - Low: Images found but confidence uncertain
   - None: No Wikipedia article found

**Output structure (updated entity):**

```json
{
  "William Dawes": {
    "entity_type": "people",
    "priority": 1.0,
    "occurrences": [...],
    "context": "...",
    "search_strategies": ["..."],
    "search_used": "William Dawes (surveyor)",
    "disambiguation": {
      "candidates": ["William Dawes (surveyor)", "William Dawes (patriot)"],
      "chosen": "William Dawes (surveyor)",
      "method": "llm"
    },
    "match_quality": "high",
    "images": [{...}]
  }
}
```

**LLM Usage:**
- Zero to many calls (only when disambiguation needed)
- Typical: 10-30% of entities require disambiguation
- Conditional: Skip if single result or no results

### Stage 3: Timeline (Enhanced)

**New behavior:** Use priority and match quality for intelligent image rotation.

**Changes:**

1. **Variety rotation**
   - For entities with multiple occurrences:
     - Use different images from `images[]` array
     - Round-robin through available images
     - Existing logic already does this, no change needed

2. **Quality filtering**
   - Option: `--min-match-quality [high|medium|low]`
   - Skip entities below threshold when placing clips
   - Allows user to say "only show high-confidence matches"

3. **Priority-based track assignment**
   - High-priority entities (people/events) → lower tracks (V2, V3) = more visible
   - Low-priority entities (places/concepts) → higher tracks (V4, V5) = less prominent

No changes to XML generation or clip placement logic.

## Component Boundaries

### New Component: tools/enrich_entities.py

**Responsibilities:**
- Read entities_map.json and SRT transcript
- Calculate priority scores
- Gather context windows from transcript
- Call LLM for search strategy generation
- Update entities_map.json with enriched metadata

**Dependencies:**
- Input: entities_map.json (from extract), SRT file path
- LLM API: OpenAI or Ollama (same as extraction)
- Output: entities_map.json (updated in-place or new file)

**Interface:**

```bash
python tools/enrich_entities.py \
  --map entities_map.json \
  --srt transcript.srt \
  --provider openai \
  --model gpt-4o-mini \
  --context-window 100 \
  --strategies-per-entity 3
```

**Exit codes:**
- 0: Success (all entities enriched)
- 1: Failure (e.g., file not found, JSON parse error)
- 2: Partial success (some LLM calls failed but others succeeded)

### Enhanced Component: tools/download_entities.py

**New responsibilities:**
- Priority filtering (skip low-priority entities based on rules)
- Multi-strategy search (iterate through search_strategies)
- Conditional disambiguation (call LLM only when needed)
- Match quality tracking (record confidence in entity metadata)

**New dependencies:**
- LLM API: For disambiguation calls
- Input: Enriched entities_map.json (with search_strategies, context)

**New interface options:**

```bash
python tools/download_entities.py \
  --map entities_map.json \
  --provider openai \
  --model gpt-4o-mini \
  --min-priority 0.5 \
  --max-disambiguation-candidates 3 \
  --skip-places-threshold 0.1
```

**Configuration:**
- `--min-priority`: Skip entities below this priority (default: 0.3, i.e., skip very low-priority concepts)
- `--max-disambiguation-candidates`: Max Wikipedia results to consider (default: 3)
- `--skip-places-threshold`: Fraction of transcript before stopping place downloads (default: 0.1, i.e., first 10%)

### Orchestration: broll.py

**New command:**

```bash
python broll.py enrich --map entities_map.json --srt transcript.srt [options]
```

**Updated pipeline command:**

```bash
python broll.py pipeline --srt transcript.srt [options]
# Internally calls: extract → enrich → download → xml
```

**Subprocess spawning:**
- Stage 1: `tools/srt_entities.py` (unchanged)
- Stage 1.5: `tools/enrich_entities.py` (new)
- Stage 2: `tools/download_entities.py` (enhanced)
- Stage 3: `generate_broll_xml.py` (enhanced)

## Data Flow: Detailed Walkthrough

### Full Pipeline Execution

```
User: python broll.py pipeline --srt video.srt --model gpt-4o-mini

┌─────────────────────────────────────────────────────────┐
│ Stage 1: Extract                                        │
│ Subprocess: tools/srt_entities.py                      │
└─────────────────────────────────────────────────────────┘
  Input:  video.srt
  Output: entities_map.json
    {
      "entities": {
        "William Dawes": {
          "entity_type": "people",
          "occurrences": [
            {"timecode": "00:03:15,000", "cue_idx": 42}
          ],
          "aliases": ["Dawes", "William Dawes"],
          "images": []
        },
        "Sydney Cove": {
          "entity_type": "places",
          "occurrences": [
            {"timecode": "00:03:18,000", "cue_idx": 43}
          ],
          "aliases": ["Sydney"],
          "images": []
        }
      }
    }

┌─────────────────────────────────────────────────────────┐
│ Stage 1.5: Enrich                                       │
│ Subprocess: tools/enrich_entities.py                   │
└─────────────────────────────────────────────────────────┘
  Input:  entities_map.json + video.srt
  Process:
    1. Calculate priorities:
       - "William Dawes" (people) → priority 1.0
       - "Sydney Cove" (places) → priority 0.3

    2. Gather context (read SRT around cue_idx 42):
       "...the First Fleet arrived at Sydney Cove in 1788.
        William Dawes was an officer and surveyor who..."

    3. Call LLM for search strategies:
       Prompt: "Entity 'William Dawes' appears in context about
               First Fleet, Sydney Cove, 1788. Suggest 3 Wikipedia
               search queries."
       Response: [
         "William Dawes (surveyor)",
         "William Dawes First Fleet",
         "William Dawes Australia 1788"
       ]

    4. Update map with enriched data

  Output: entities_map.json (enriched)
    {
      "subject": "First Fleet Australia",
      "entities": {
        "William Dawes": {
          "entity_type": "people",
          "priority": 1.0,
          "occurrences": [...],
          "context": "...First Fleet...Sydney Cove 1788...surveyor...",
          "search_strategies": [
            "William Dawes (surveyor)",
            "William Dawes First Fleet",
            "William Dawes Australia 1788"
          ],
          "images": []
        },
        "Sydney Cove": {
          "entity_type": "places",
          "priority": 0.3,
          "occurrences": [...],
          "context": "...arrived at Sydney Cove in 1788...",
          "search_strategies": [
            "Sydney Cove",
            "Sydney Cove 1788",
            "Sydney Cove First Fleet"
          ],
          "images": []
        }
      }
    }

┌─────────────────────────────────────────────────────────┐
│ Stage 2: Download                                       │
│ Subprocess: tools/download_entities.py                 │
└─────────────────────────────────────────────────────────┘
  Input:  entities_map.json (enriched)
  Process per entity:

  Entity: "William Dawes" (priority 1.0 → proceed)
    Try strategy 1: "William Dawes (surveyor)"
      → Wikipedia API returns 2 results:
         1. "William Dawes (surveyor)" (1762-1836, Australia)
         2. "William Dawes (marine)" (1762-1836, same person)
      → Only 1 unique article → high confidence → proceed

    Download images from "William Dawes (surveyor)"
      → 3 images found, 2 public domain, 1 CC-BY
      → Saved to /output/William Dawes/

    Record match quality: "high"

  Entity: "Sydney Cove" (priority 0.3 → check threshold)
    Occurrence at timecode 00:03:18 (3m18s / 45m video = 7%)
    → Within first 10% of transcript → proceed

    Try strategy 1: "Sydney Cove"
      → Wikipedia API returns 1 result: "Sydney Cove"
      → Single result → proceed without disambiguation

    Download images from "Sydney Cove"
      → 5 images found, all public domain
      → Saved to /output/Sydney Cove/

    Record match quality: "high"

  Output: entities_map.json (with images)
    {
      "subject": "First Fleet Australia",
      "entities": {
        "William Dawes": {
          "entity_type": "people",
          "priority": 1.0,
          "context": "...",
          "search_strategies": [...],
          "search_used": "William Dawes (surveyor)",
          "match_quality": "high",
          "images": [
            {
              "path": "/output/William Dawes/public_domain/image1.jpg",
              "license": "public_domain",
              "source_url": "..."
            },
            ...
          ]
        },
        "Sydney Cove": {
          "entity_type": "places",
          "priority": 0.3,
          "context": "...",
          "search_strategies": [...],
          "search_used": "Sydney Cove",
          "match_quality": "high",
          "images": [...]
        }
      }
    }

┌─────────────────────────────────────────────────────────┐
│ Stage 3: Timeline                                       │
│ Subprocess: generate_broll_xml.py                      │
└─────────────────────────────────────────────────────────┘
  Input:  entities_map.json (with images)
  Process:
    For each entity occurrence:
      - Calculate frame position from timecode
      - Select next image (round-robin through entity's images array)
      - Assign track (prefer lower tracks for high-priority entities)
      - Write clip to FCP XML

  Output: broll_timeline.xml
```

## Suggested Build Order

Build in phases to maintain working pipeline at each step.

### Phase 1: Enrichment Foundation (No Behavior Change)

**Goal:** Add enrichment stage without changing download behavior.

**Tasks:**
1. Create `tools/enrich_entities.py` skeleton
   - Read entities_map.json and SRT
   - Calculate priority scores (deterministic)
   - Gather context windows (no LLM, just text extraction)
   - Write priority and context back to map
2. Add `broll.py enrich` command
3. Update `broll.py pipeline` to include enrich step
4. Test: Pipeline should still work, download stage ignores new fields

**Validation:** Run pipeline end-to-end, verify entities_map.json has priority/context fields but images still download correctly.

### Phase 2: Search Strategy Generation (Better Searches)

**Goal:** LLM generates multiple search queries; download tries them in sequence.

**Tasks:**
1. Add LLM call to `enrich_entities.py` for search strategy generation
2. Update `download_entities.py` to iterate through search_strategies
   - Try first strategy; if no results, try second; etc.
   - Still take first Wikipedia result (no disambiguation yet)
3. Add `search_used` tracking to entity metadata

**Validation:** Compare before/after: entities that previously failed to find images should now succeed.

### Phase 3: Priority-Based Filtering (Fewer Wasted Downloads)

**Goal:** Skip low-priority entities based on rules.

**Tasks:**
1. Add priority filtering logic to `download_entities.py`
   - Skip places unless early or frequent
   - Skip concepts unless multi-mention
2. Add `--min-priority` and `--skip-places-threshold` flags
3. Add skipped entity logging

**Validation:** Count entities downloaded before/after; verify places are skipped appropriately.

### Phase 4: Disambiguation (Correct Article Selection)

**Goal:** When multiple Wikipedia articles match, LLM picks the right one.

**Tasks:**
1. Modify `download_entities.py` search logic:
   - Get top 3 Wikipedia results per strategy
   - If 2+ results, call LLM for disambiguation
2. Add disambiguation result tracking to entity metadata
3. Add `--max-disambiguation-candidates` flag

**Validation:** Manually inspect entities with disambiguation data; verify LLM chose correctly.

### Phase 5: Match Quality & Variety (Polish)

**Goal:** Track confidence and use it in timeline generation.

**Tasks:**
1. Add `match_quality` scoring to `download_entities.py`
2. Update `generate_broll_xml.py` to use quality for filtering
3. Add priority-based track assignment
4. Add `--min-match-quality` flag to xml generation

**Validation:** Generate timeline with `--min-match-quality high` and verify low-confidence entities excluded.

## Patterns to Follow

### Pattern 1: Enrichment as Separate Stage

**What:** Augment data in a dedicated stage before consumption.

**Why:**
- **Separation of concerns**: Entity extraction focuses on what; enrichment focuses on how to find it
- **Resume-friendly**: If enrichment fails, can restart without re-extracting entities
- **Testable**: Can validate search strategies without downloading images
- **Cacheable**: Enrichment results are deterministic given same transcript/entities

**Example:**
```python
# tools/enrich_entities.py
def enrich_entity(entity_name, entity_data, context, llm_client):
    """Generate search strategies for a single entity."""
    prompt = f"""
    Entity: {entity_name}
    Type: {entity_data['entity_type']}
    Context: {context}

    Suggest 3 Wikipedia search queries that would find the correct
    article for this entity, ordered by likelihood of success.
    Return as JSON array of strings.
    """

    response = llm_client.call(prompt)
    strategies = json.loads(response)

    entity_data['search_strategies'] = strategies
    entity_data['context'] = context[:200]  # Truncate for storage

    return entity_data
```

### Pattern 2: Multi-Strategy Search with Fallback

**What:** Try multiple search queries in sequence until one succeeds.

**Why:**
- **Robustness**: Single search failure doesn't block image download
- **Contextual**: LLM-generated strategies are more likely to match Wikipedia article titles
- **Logged**: Track which strategy worked for debugging

**Example:**
```python
# tools/download_entities.py
def search_with_strategies(entity_name, strategies, wikipedia_api):
    """Try multiple search strategies until one returns results."""
    for i, query in enumerate(strategies):
        print(f"  Strategy {i+1}/{len(strategies)}: '{query}'")
        results = wikipedia_api.search(query, limit=3)

        if results:
            return {
                'strategy_used': query,
                'strategy_index': i,
                'results': results
            }

    # All strategies failed
    return {
        'strategy_used': None,
        'strategy_index': -1,
        'results': []
    }
```

### Pattern 3: Conditional Disambiguation

**What:** Only call LLM for disambiguation when multiple Wikipedia results exist.

**Why:**
- **Cost-efficient**: Avoid unnecessary LLM calls (typical: 10-30% of entities need disambiguation)
- **Fast**: Single-result cases skip disambiguation entirely
- **Confident**: Record disambiguation method for quality tracking

**Example:**
```python
# tools/download_entities.py
def disambiguate_article(entity_name, context, candidates, llm_client):
    """Use LLM to pick correct Wikipedia article from candidates."""
    if len(candidates) == 1:
        return {'chosen': candidates[0], 'method': 'single_result'}

    if len(candidates) == 0:
        return {'chosen': None, 'method': 'no_results'}

    # Multiple candidates → LLM disambiguation needed
    prompt = f"""
    Entity: {entity_name}
    Context: {context}

    Which Wikipedia article matches this entity?
    Candidates:
    {format_candidates(candidates)}

    Return only the title of the best match.
    """

    response = llm_client.call(prompt)
    chosen_title = response.strip()

    return {
        'chosen': chosen_title,
        'method': 'llm',
        'candidates': [c['title'] for c in candidates]
    }
```

### Pattern 4: Priority-Based Processing

**What:** Calculate entity priority early; use it to skip or de-prioritize entities.

**Why:**
- **Performance**: Avoid downloading images for entities that won't be used
- **Quality**: Focus bandwidth on high-value entities (people, events)
- **Configurable**: User can adjust thresholds based on their needs

**Example:**
```python
# tools/enrich_entities.py
def calculate_priority(entity_type, occurrence_count, first_mention_offset):
    """Calculate entity priority score (0.0 to 1.0)."""
    base_priority = {
        'people': 1.0,
        'events': 0.9,
        'concepts': 0.6,
        'places': 0.3
    }.get(entity_type, 0.5)

    # Boost for frequent mentions
    frequency_boost = min(0.2, occurrence_count * 0.05)

    # Boost for early mentions (first 10% of transcript)
    early_boost = 0.1 if first_mention_offset < 0.1 else 0.0

    return min(1.0, base_priority + frequency_boost + early_boost)

# tools/download_entities.py
def should_download_entity(entity_data, min_priority=0.3):
    """Determine if entity should have images downloaded."""
    priority = entity_data.get('priority', 0.5)
    entity_type = entity_data.get('entity_type', '')

    if priority < min_priority:
        return False

    # Additional rules for places
    if entity_type == 'places':
        occurrences = entity_data.get('occurrences', [])
        # Skip if only mentioned once and not early
        if len(occurrences) == 1:
            first_offset = calculate_offset(occurrences[0])
            if first_offset > 0.1:  # Not in first 10%
                return False

    return True
```

### Pattern 5: Match Quality Tracking

**What:** Record how confident we are that the downloaded images match the entity.

**Why:**
- **User visibility**: User can review low-quality matches before publishing
- **Filtering**: Timeline generation can exclude uncertain matches
- **Debugging**: Understand where disambiguation succeeds/fails

**Example:**
```python
# tools/download_entities.py
def calculate_match_quality(search_result, disambiguation_result):
    """Determine match quality based on search and disambiguation."""
    if disambiguation_result['method'] == 'single_result':
        return 'high'

    if disambiguation_result['method'] == 'llm':
        # LLM confirmed one of multiple candidates
        if disambiguation_result['chosen'] in disambiguation_result['candidates']:
            return 'high'
        return 'medium'

    if disambiguation_result['method'] == 'no_results':
        return 'none'

    # Multiple strategies tried before success
    if search_result['strategy_index'] > 0:
        return 'medium'

    return 'low'
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: LLM in Hot Path

**What:** Calling LLM during download iteration for every entity.

**Why bad:**
- **Latency**: Blocks download until LLM responds (200-2000ms per call)
- **Complexity**: Download stage now has LLM dependency and API key management
- **Error handling**: LLM failures mixed with download failures

**Instead:** Pre-compute LLM-dependent data in enrichment stage; download consumes results.

### Anti-Pattern 2: Synchronous Disambiguation

**What:** Calling LLM for disambiguation before attempting any downloads.

**Why bad:**
- **Unnecessary work**: Disambiguates entities that have only 1 Wikipedia result
- **Wasted API calls**: 70-90% of entities don't need disambiguation
- **Slow**: Adds latency even when not needed

**Instead:** Disambiguate conditionally only when multiple results exist.

### Anti-Pattern 3: Inline Priority Decisions

**What:** Hardcoding priority rules in download stage without exposing them.

**Why bad:**
- **Inflexible**: User can't adjust thresholds (e.g., "I want more place images")
- **Opaque**: User doesn't know why entity was skipped
- **Untestable**: Can't validate priority logic independently

**Instead:** Calculate priorities in enrichment stage; expose as config flags in download stage.

### Anti-Pattern 4: Context Re-Parsing

**What:** Each stage re-reads SRT to extract context around entities.

**Why bad:**
- **Inefficient**: SRT parsing done multiple times
- **Inconsistent**: Different stages may extract different context windows
- **Error-prone**: SRT path must be passed to every stage

**Instead:** Extract context once in enrichment stage; store in entities_map.json.

### Anti-Pattern 5: Monolithic JSON Update

**What:** Enrichment and download both write to entities_map.json simultaneously.

**Why bad:**
- **Race conditions**: Parallel writes corrupt JSON
- **Lost data**: One stage overwrites other's changes
- **Non-atomic**: Partial writes leave invalid JSON

**Instead:** Each stage reads, modifies, writes atomically; stages run sequentially.

## Scalability Considerations

### At 100 entities (typical podcast episode)

| Concern | Approach |
|---------|----------|
| **Enrichment time** | Sequential LLM calls: ~100 × 500ms = 50s. Acceptable. |
| **Download time** | Parallel (4 workers): ~100 / 4 × 3s = 75s. Acceptable. |
| **Disambiguation calls** | ~30% need it: 30 × 500ms = 15s. Acceptable. |
| **Total pipeline** | Extract (2-3 min) + Enrich (1 min) + Download (2 min) + XML (5s) = **5-6 minutes** |

**Optimization:** None needed. Current approach scales fine.

### At 500 entities (long documentary)

| Concern | Approach |
|---------|----------|
| **Enrichment time** | 500 × 500ms = 250s (4 min). Still acceptable. |
| **Download time** | 500 / 4 × 3s = 375s (6 min). Acceptable. |
| **Disambiguation calls** | 150 × 500ms = 75s (1.25 min). Acceptable. |
| **Total pipeline** | Extract (10 min) + Enrich (5 min) + Download (7 min) + XML (10s) = **22 minutes** |

**Optimization:** Consider parallel LLM calls in enrichment (if API supports). Could reduce enrichment time by 4× with 4 workers.

### At 1000+ entities (rare, multi-hour content)

| Concern | Approach |
|---------|----------|
| **Enrichment time** | 1000 × 500ms = 500s (8 min) sequential. |
| **Parallel enrichment** | With 8 workers: 1000 / 8 × 500ms = 62s (1 min). Much better. |
| **Download time** | 1000 / 8 × 3s = 375s (6 min) with 8 workers. |
| **Disambiguation calls** | 300 × 500ms = 150s (2.5 min). Acceptable. |
| **Total pipeline** | Extract (20 min) + Enrich (1 min) + Download (6 min) + XML (15s) = **27 minutes** with parallel enrichment |

**Optimization required:**
1. Add `--parallel` flag to `enrich_entities.py` (use ThreadPoolExecutor like download stage)
2. Increase download workers to 8 (from 4)
3. Batch LLM calls if provider supports (OpenAI batch API)

## Configuration Schema

### New Configuration Fields (broll_config.yaml)

```yaml
# Enrichment stage
enrichment:
  strategies_per_entity: 3
  context_window_size: 100  # words
  parallel_workers: 1  # Set to 4-8 for large transcripts

  # Priority scoring
  priority_weights:
    people: 1.0
    events: 0.9
    concepts: 0.6
    places: 0.3

  # Boosts
  frequency_boost_per_mention: 0.05
  early_mention_boost: 0.1  # If in first 10% of transcript

# Download stage
download:
  min_priority: 0.3  # Skip entities below this
  skip_places_threshold: 0.1  # Skip places after first 10% of transcript
  max_disambiguation_candidates: 3
  parallel_workers: 4

  # Places-specific rules
  places:
    require_min_mentions: 1  # or 2, to skip one-off places
    allow_late_mentions: false  # Only download if mentioned early

# Timeline stage
timeline:
  min_match_quality: "medium"  # high | medium | low
  priority_track_assignment: true  # High priority → lower tracks
```

### CLI Flag Mapping

```bash
# Enrichment
python tools/enrich_entities.py \
  --map entities_map.json \
  --srt transcript.srt \
  --provider openai \
  --model gpt-4o-mini \
  --strategies-per-entity 3 \
  --context-window 100 \
  --parallel 4

# Download
python tools/download_entities.py \
  --map entities_map.json \
  --provider openai \
  --model gpt-4o-mini \
  --min-priority 0.3 \
  --skip-places-threshold 0.1 \
  --max-disambiguation-candidates 3 \
  --parallel 4

# Timeline
python generate_broll_xml.py \
  entities_map.json \
  --output broll_timeline.xml \
  --min-match-quality medium \
  --priority-tracks
```

## Error Handling Strategies

### Enrichment Stage Failures

**Scenario 1: LLM API timeout**
- **Detection**: HTTP timeout (60s) on search strategy generation
- **Response**: Log warning, use fallback strategy: `[canonical_name]`
- **Continue**: Yes, enrich remaining entities
- **Exit code**: 0 (success) if ≥90% enriched, 2 (partial) if <90%

**Scenario 2: Invalid LLM response**
- **Detection**: JSON parse failure on search strategies
- **Response**: Log warning, use fallback strategy: `[canonical_name]`
- **Continue**: Yes
- **Exit code**: 0 or 2 (same as above)

**Scenario 3: SRT file not found**
- **Detection**: FileNotFoundError when gathering context
- **Response**: Print error to stderr
- **Continue**: No
- **Exit code**: 1 (failure)

### Download Stage Failures

**Scenario 1: Disambiguation LLM failure**
- **Detection**: HTTP timeout or invalid response
- **Response**: Fall back to first Wikipedia result
- **Record**: `disambiguation: {method: 'fallback', reason: 'llm_timeout'}`
- **Match quality**: Downgrade to 'medium'
- **Continue**: Yes

**Scenario 2: All search strategies fail**
- **Detection**: No Wikipedia results for any strategy
- **Response**: Log entity as skipped
- **Record**: `match_quality: 'none'`
- **Continue**: Yes
- **Exit code**: 0 (success, just no images for this entity)

**Scenario 3: Wikipedia API rate limit**
- **Detection**: HTTP 429 response
- **Response**: Exponential backoff, retry (existing logic)
- **Continue**: Yes, with delays
- **Exit code**: 0 if eventually succeeds, 1 if max retries exceeded

### Timeline Stage Failures

**Scenario 1: Entity has no images**
- **Detection**: `images: []` in entity data
- **Response**: Skip entity in timeline generation
- **Continue**: Yes
- **Exit code**: 0 (timeline generated, just fewer clips)

**Scenario 2: All entities below min match quality**
- **Detection**: All entities filtered out by `--min-match-quality`
- **Response**: Print warning "No entities meet quality threshold"
- **Continue**: Yes, generate empty timeline
- **Exit code**: 0

## Interface Contracts

### entities_map.json Schema (Enriched)

```json
{
  "source_srt": "/path/to/transcript.srt",
  "subject": "Optional[str] - overall transcript subject",
  "entities": {
    "EntityName": {
      "entity_type": "people | places | events | concepts",
      "aliases": ["List[str] - alternate names"],
      "occurrences": [
        {
          "timecode": "HH:MM:SS,mmm",
          "cue_idx": "int"
        }
      ],

      // Added by enrichment stage
      "priority": "float 0.0-1.0",
      "context": "str - consolidated context window",
      "search_strategies": ["List[str] - LLM-generated queries"],

      // Added by download stage
      "search_used": "Optional[str] - which strategy succeeded",
      "disambiguation": {
        "method": "single_result | llm | fallback | no_results",
        "candidates": ["Optional[List[str]]"],
        "chosen": "Optional[str]"
      },
      "match_quality": "high | medium | low | none",
      "images": [
        {
          "path": "str - filesystem path",
          "filename": "str",
          "category": "str - license category",
          "license_short": "str",
          "license_url": "str",
          "source_url": "str"
        }
      ]
    }
  }
}
```

### LLM Prompt Templates

**Search Strategy Generation:**

```python
SEARCH_STRATEGY_PROMPT = """
You are helping find the correct Wikipedia article for an entity mentioned in a video transcript.

Entity: {entity_name}
Entity Type: {entity_type}
Context from transcript:
{context}

Suggest {num_strategies} Wikipedia search queries that would find the correct article for this entity, ordered by likelihood of success. Consider:
- Disambiguation qualifiers (parentheses) used by Wikipedia
- Alternative phrasings
- Historical context if this is a historical topic
- Geographic qualifiers if location is relevant

Return ONLY a JSON array of strings, no explanation:
["query1", "query2", "query3"]
"""
```

**Disambiguation:**

```python
DISAMBIGUATION_PROMPT = """
You are helping identify which Wikipedia article matches an entity from a video transcript.

Entity: {entity_name}
Context from transcript:
{context}

Wikipedia search returned multiple articles. Which one matches the entity in the transcript?

Candidates:
{formatted_candidates}

Return ONLY the exact title of the best match, nothing else.
"""

def format_candidates(candidates):
    """Format candidate articles for LLM."""
    lines = []
    for i, candidate in enumerate(candidates, 1):
        title = candidate['title']
        snippet = candidate.get('snippet', '')[:200]
        lines.append(f"{i}. {title}")
        if snippet:
            lines.append(f"   {snippet}")
    return '\n'.join(lines)
```

## Dependencies Between Components

### Build Order Graph

```
Phase 1: Enrichment Foundation
  ├─ tools/enrich_entities.py (new)
  │  ├─ Read entities_map.json
  │  ├─ Read SRT file
  │  ├─ Calculate priority (deterministic)
  │  └─ Gather context (text extraction)
  │
  └─ broll.py (modify)
     └─ Add `enrich` command

Phase 2: Search Strategies
  ├─ tools/enrich_entities.py (enhance)
  │  └─ Add LLM call for strategy generation
  │
  └─ tools/download_entities.py (modify)
     ├─ Read search_strategies from entity
     ├─ Iterate through strategies
     └─ Record search_used

Phase 3: Priority Filtering
  └─ tools/download_entities.py (enhance)
     ├─ Add should_download_entity()
     └─ Add priority filtering logic

Phase 4: Disambiguation
  └─ tools/download_entities.py (enhance)
     ├─ Get multiple Wikipedia results
     ├─ Add LLM call for disambiguation
     └─ Record disambiguation metadata

Phase 5: Match Quality
  ├─ tools/download_entities.py (enhance)
  │  └─ Add match_quality scoring
  │
  └─ generate_broll_xml.py (modify)
     ├─ Filter by min_match_quality
     └─ Priority-based track assignment
```

### Critical Path

```
User invokes: python broll.py pipeline --srt video.srt

Critical path (sequential):
1. Extract entities (cannot parallelize, requires LLM per cue)
2. Enrich entities (can parallelize LLM calls in future)
3. Download images (already parallelized with ThreadPoolExecutor)
4. Generate timeline (fast, I/O bound)

Total time: ~5-6 minutes for typical 100-entity project

Optimization potential:
- Phase 2 (Enrich): Parallelize LLM calls → 4× speedup
- Phase 3 (Download): Already parallel, could increase workers
- Bottleneck remains: Phase 1 (Extract) must be sequential
```

## Testing Strategy

### Unit Tests

**tools/enrich_entities.py:**
- `test_calculate_priority()` - verify priority scoring logic
- `test_gather_context()` - verify context window extraction
- `test_search_strategy_prompt()` - verify prompt template formatting

**tools/download_entities.py:**
- `test_should_download_entity()` - verify filtering rules
- `test_multi_strategy_search()` - verify fallback logic
- `test_calculate_match_quality()` - verify scoring

### Integration Tests

**Stage 1.5 (Enrich):**
- Given: entities_map.json with 3 entities
- When: Run enrich command
- Then: All entities have priority, context, search_strategies

**Stage 2 (Download with strategies):**
- Given: Enriched entities_map.json
- When: Run download command
- Then: Entities have search_used, images, match_quality

**Full pipeline:**
- Given: SRT transcript
- When: Run `broll.py pipeline`
- Then: XML timeline generated with appropriate entities

### Manual Validation

**Disambiguation accuracy:**
- Run pipeline on transcript with ambiguous entities (e.g., "William Dawes", "Paris" in different contexts)
- Review `disambiguation` field in entities_map.json
- Verify LLM chose correct article

**Priority filtering:**
- Run pipeline on long transcript with many place mentions
- Count entities downloaded vs. skipped
- Verify places are only downloaded early in transcript

**Match quality:**
- Generate timeline with `--min-match-quality high`
- Verify only high-confidence entities appear
- Compare against `--min-match-quality low`

## Migration Path

For existing users with current pipeline:

### Backward Compatibility

**Option 1: Graceful degradation**
- If entities_map.json lacks `search_strategies`, use `[canonical_name]` as fallback
- If entities_map.json lacks `priority`, assume priority 1.0 (download everything)
- Result: New download stage works with old entities_map.json

**Option 2: Explicit migration**
- Add `broll.py migrate` command to enrich old entities_map.json
- User runs: `python broll.py migrate --map old_entities_map.json --srt video.srt`
- Result: Old map upgraded to new schema

**Recommendation:** Option 1 (graceful degradation) for ease of adoption.

### Rollout Plan

**Week 1-2: Phase 1 (Foundation)**
- Ship enrichment stage (priority + context, no LLM)
- Update pipeline to include enrich step
- Release as v0.2.0

**Week 3-4: Phase 2 (Search strategies)**
- Add LLM search strategy generation
- Update download to use strategies
- Release as v0.3.0

**Week 5-6: Phase 3 (Priority filtering)**
- Add priority-based download filtering
- Release as v0.4.0

**Week 7-8: Phase 4 (Disambiguation)**
- Add LLM disambiguation
- Release as v0.5.0

**Week 9-10: Phase 5 (Match quality)**
- Add quality tracking and timeline filtering
- Release as v1.0.0 (stable)

## Conclusion

The proposed four-stage architecture maintains the pipeline's checkpoint-based design while adding LLM-powered intelligence where it matters most. By inserting an enrichment stage, we:

1. **Generate better search queries** (LLM suggests contextual Wikipedia queries)
2. **Disambiguate correctly** (LLM compares candidates against transcript)
3. **Prioritize strategically** (Download high-value entities first, skip low-value)
4. **Track confidence** (User can filter by match quality)

The architecture preserves existing strengths:
- Subprocess isolation
- Fail-fast error handling
- Resume-from-checkpoint capability
- Parallel execution where appropriate

Build order follows a low-risk incremental approach: each phase delivers value independently and maintains backward compatibility.

---

*Architecture research completed: 2026-01-25*
*Confidence: HIGH (based on existing codebase analysis and established patterns)*
