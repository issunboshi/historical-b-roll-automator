# Phase 1: Enrichment Foundation - Research

**Researched:** 2026-01-25
**Domain:** Python data enrichment pipelines, transcript processing, priority scoring
**Confidence:** HIGH

## Summary

This phase adds an enrichment stage between entity extraction and download in the existing B-roll pipeline. The enrichment augments entity metadata with priority scores and transcript context before attempting Wikipedia image downloads. Research focused on three key areas: (1) transcript context extraction using sliding windows, (2) priority scoring formulas with diminishing returns, and (3) batch processing patterns for LLM-based enrichment.

The existing codebase uses Python 3.13 with a checkpoint-based architecture where each stage reads/writes JSON files (entities_map.json). The enrichment stage should follow this pattern: read entities_map.json, enrich entities in batches, write enriched_entities.json as a new checkpoint. The pipeline already handles partial failures gracefully (skips entities without images), so the enrichment stage should adopt the same resilience pattern.

**Primary recommendation:** Use standard library features (no heavy dependencies), implement enrichment as a separate function callable from broll.py pipeline command, store enriched data in separate checkpoint file, use itertools.batched() for chunking (Python 3.12+), and calculate priority scores with simple formulas avoiding ML libraries.

## Standard Stack

The existing codebase uses minimal dependencies, so enrichment should follow suit.

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python standard library | 3.13+ | Core processing (json, re, itertools) | Already required, zero dependencies |
| requests | >=2.32.0 | LLM API calls (existing) | Already in requirements.txt |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.x (optional) | Schema validation if needed | Only if strict validation required; likely overkill for this phase |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Standard library | pandas | Adds heavy dependency for simple JSON manipulation; unnecessary |
| Manual JSON updates | SQLite checkpoints | More complex; JSON files work well for pipeline checkpointing |
| Custom chunking | numpy batching | Adds dependency; itertools.batched() sufficient for entity batching |

**Installation:**
```bash
# No new dependencies required
# All functionality available in Python 3.13 standard library + existing requirements.txt
```

## Architecture Patterns

### Recommended Project Structure
```
tools/
├── srt_entities.py          # Existing: extraction stage
├── enrich_entities.py        # NEW: enrichment stage (this phase)
├── download_entities.py      # Existing: download stage
broll.py                       # Update: add enrich step to pipeline
```

### Pattern 1: Checkpoint-Based Pipeline Stages

**What:** Each stage reads from previous checkpoint, processes data, writes new checkpoint file. Failures leave previous checkpoint intact.

**When to use:** Multi-stage data pipelines where each stage is expensive and should be independently resumable.

**Example:**
```python
# Existing pattern from tools/download_entities.py
def main():
    # Read checkpoint from previous stage
    with open(args.map, "r", encoding="utf-8") as f:
        entities_map = json.load(f)

    entities = entities_map.get("entities", {})

    # Process entities (with partial failure handling)
    for entity_name, payload in entities.items():
        try:
            # Process entity
            payload["images"] = download_images(entity_name)
        except Exception:
            # Log failure but continue processing
            continue

    # Write updated checkpoint atomically
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)
```

**For enrichment stage:** Follow same pattern but write to enriched_entities.json as separate checkpoint.

### Pattern 2: Sliding Window Context Extraction

**What:** Extract surrounding text context for each entity mention using character/word-based windows.

**When to use:** When entities need contextual information from their mentions in the source transcript.

**Example:**
```python
# Pseudo-code based on research
def extract_context_window(text: str, mention_start: int, mention_end: int,
                          window_words: int = 125) -> str:
    """Extract ~125 words around mention (paragraph-level context)."""
    # Find sentence boundaries before and after mention
    # Expand to include ~window_words/2 on each side
    # Return context string with mention highlighted
    pass

def merge_contexts(contexts: list[str]) -> str:
    """Merge multiple context windows, deduplicating overlaps."""
    # Simple approach: concatenate with separator
    # Advanced: detect overlap, deduplicate consecutive windows
    return " ... ".join(contexts)
```

**Implementation notes:**
- SRT cues already provide mention positions (timecode, cue_idx)
- Parse full transcript text, map cue positions to character offsets
- For each occurrence, extract window, deduplicate overlaps
- Merge all contexts into single field per entity

### Pattern 3: Diminishing Returns Priority Scoring

**What:** Calculate priority scores using base weights and multipliers with diminishing returns.

**When to use:** When combining multiple factors (type, mentions, position) into single priority score.

**Example:**
```python
# Based on Phase 1 decisions and research on diminishing returns
TYPE_WEIGHTS = {
    "people": 1.0,      # Highest priority
    "events": 0.9,      # Need context to avoid random images
    "organizations": 0.7,
    "concepts": 0.6,
    "places": 0.3       # Lowest priority
}

def mention_multiplier(mention_count: int) -> float:
    """Diminishing returns: 1→1.0x, 2→1.3x, 3→1.5x, 4+→1.6x"""
    if mention_count == 1:
        return 1.0
    elif mention_count == 2:
        return 1.3
    elif mention_count == 3:
        return 1.5
    else:  # 4+
        return 1.6

def position_multiplier(first_mention_position_pct: float) -> float:
    """Boost entities in first 20% of transcript by 1.1x"""
    return 1.1 if first_mention_position_pct <= 0.20 else 1.0

def calculate_priority(entity_type: str, mention_count: int,
                      first_position_pct: float) -> float:
    """Calculate priority score (0.0-1.2 range, cap at 1.2)"""
    base = TYPE_WEIGHTS.get(entity_type, 0.5)
    mentions = mention_multiplier(mention_count)
    position = position_multiplier(first_position_pct)

    score = base * mentions * position
    return min(score, 1.2)  # Cap at 1.2
```

### Pattern 4: Batch Processing for LLM Calls

**What:** Process entities in chunks of 10-20 to balance speed and resilience.

**When to use:** When making many LLM calls where batching reduces API overhead.

**Example:**
```python
# Using Python 3.12+ itertools.batched()
from itertools import batched

def enrich_entities_batch(entities_list: list[dict], llm_client) -> list[dict]:
    """Process entities in batches of 15."""
    enriched = []

    for batch in batched(entities_list, 15):
        try:
            # LLM call with all batch entities
            result = llm_client.enrich_batch(batch)
            enriched.extend(result)
        except Exception as e:
            # Mark batch as failed, continue
            for entity in batch:
                entity["enrichment_status"] = "failed"
            enriched.extend(batch)

    return enriched
```

**For Python 3.11 or earlier:**
```python
# Fallback chunking using itertools
from itertools import islice

def batched(iterable, n):
    """Batch data into lists of length n. Last batch may be shorter."""
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch
```

### Anti-Patterns to Avoid

- **Loading entire transcript into memory multiple times:** Parse once, cache character offset mappings
- **Regex-based SRT parsing:** Use existing parse_srt() from tools/srt_entities.py (already handles multiple formats)
- **Synchronous sequential LLM calls:** Batch requests to reduce latency
- **Overwriting original entities_map.json:** Create separate enriched_entities.json checkpoint
- **Complex ML models for scoring:** Simple formulas sufficient for priority calculation

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic JSON writes | Manual write + rename | Atomic write pattern with temp file | Prevents corruption on failure; existing pattern in codebase |
| SRT parsing | New parser | Existing parse_srt() in tools/srt_entities.py | Already handles 3+ SRT formats, frame timecodes |
| Entity mention tracking | Custom data structure | Existing entities_map structure | Already has occurrences[], timecode tracking |
| Text overlap detection | String matching | Simple span comparison with tuples | Character offsets sufficient for overlap detection |
| Batching iterables | Manual chunking loops | itertools.batched() (Python 3.12+) | Built-in, memory-efficient, well-tested |

**Key insight:** The existing codebase has robust SRT parsing and entity tracking. Enrichment should augment this structure, not replace it. Avoid "clever" optimizations—clear, maintainable code that matches existing patterns is better.

## Common Pitfalls

### Pitfall 1: Transcript Position Calculation Off-by-One Errors

**What goes wrong:** Calculating percentage position incorrectly (using cue index instead of time, or wrong denominator).

**Why it happens:** SRT files have both cue indices (1-based sequence numbers) and timecodes (actual time positions). First 20% should be based on time, not cue count.

**How to avoid:**
- Convert all timecodes to seconds (HH:MM:SS,mmm → float)
- Calculate total transcript duration from last cue end time
- For each entity's first mention: `position_pct = first_mention_seconds / total_duration`
- Store first_mention_position_pct in enriched metadata

**Warning signs:**
- Priority scores seem wrong for obviously early/late entities
- Position percentages don't match expected values (0.0-1.0 range)

### Pitfall 2: Context Window Overlap Creates Duplicate Text

**What goes wrong:** When entity mentioned multiple times in close proximity, context windows overlap, creating bloated merged context.

**Why it happens:** Naive concatenation without checking for duplicate spans.

**How to avoid:**
```python
# Track spans to detect overlaps
def deduplicate_context_spans(spans: list[tuple[int, int, str]]) -> str:
    """Spans are (start_offset, end_offset, context_text)."""
    # Sort by start position
    spans.sort(key=lambda x: x[0])

    merged = []
    for start, end, text in spans:
        if not merged or start >= merged[-1][1]:
            # No overlap, add new span
            merged.append((start, end, text))
        else:
            # Overlap detected, extend previous span
            prev_start, prev_end, prev_text = merged[-1]
            # Only extend if new span adds content
            if end > prev_end:
                # Merge logic here
                pass

    return " ... ".join(text for _, _, text in merged)
```

**Warning signs:**
- Merged context strings are unexpectedly long (>500 words)
- Same sentences appear multiple times in context field

### Pitfall 3: LLM Batch Calls Fail Silently

**What goes wrong:** Batch LLM call fails, entire batch marked as failed, no partial recovery.

**Why it happens:** Exception handling at batch level instead of entity level.

**How to avoid:**
- Catch exceptions at batch level, mark batch as "needs_retry"
- Implement per-entity fallback: retry failed batches one-by-one
- Store enrichment_status per entity: "success", "failed", "partial"

```python
def enrich_with_fallback(entities_batch, llm_client):
    try:
        # Try batch call
        return llm_client.enrich_batch(entities_batch)
    except Exception as batch_error:
        # Fallback: process individually
        results = []
        for entity in entities_batch:
            try:
                result = llm_client.enrich_single(entity)
                results.append(result)
            except Exception:
                entity["enrichment_status"] = "failed"
                results.append(entity)
        return results
```

**Warning signs:**
- Entire enrichment stage fails on first batch error
- Success rate is binary (100% or 0%, nothing in between)

### Pitfall 4: Entity Type Classification Inconsistent with Extraction

**What goes wrong:** Enrichment LLM classifies entity as different type than extraction stage, creating confusion.

**Why it happens:** Different prompts, different LLM models, or ambiguous entities.

**How to avoid:**
- Phase 1 CONTEXT decision: use extraction type if confident, only call LLM for ambiguous cases
- Check entity_type field from extraction: if not "MISC" or empty, keep it
- LLM enrichment only classifies when extraction type is missing/ambiguous
- Standardize type names: Person→people, Place→places (lowercase plural for consistency)

```python
def normalize_entity_type(extracted_type: str, entity_name: str,
                         context: str, llm_client) -> str:
    """Return normalized type, calling LLM only if needed."""
    # Map extraction types to normalized form
    TYPE_MAP = {
        "Person": "people", "People": "people",
        "Place": "places", "Location": "places",
        "Organization": "organizations", "Org": "organizations",
        "Event": "events", "Date": "events",
        "Concept": "concepts"
    }

    normalized = TYPE_MAP.get(extracted_type)
    if normalized:
        return normalized

    # Ambiguous or missing: call LLM
    if extracted_type in ("MISC", "", None):
        return llm_classify_type(entity_name, context, llm_client)

    return "concepts"  # Default fallback
```

**Warning signs:**
- Same entity has different types in extraction vs enrichment
- Type distribution changes dramatically after enrichment

### Pitfall 5: Enrichment Stage Takes Too Long

**What goes wrong:** Enrichment adds 5-10 minutes to pipeline runtime for typical transcript.

**Why it happens:** Too many LLM calls, poor batching, synchronous processing.

**How to avoid:**
- Batch size 15-20 entities per LLM call (balance latency and failure isolation)
- Minimize LLM calls: only classify ambiguous types (expect 10-30% of entities)
- Context extraction is pure Python (no API calls), should be fast
- Priority scoring is pure math (no API calls), instant

**Expected performance:**
- 50 entities, 10% ambiguous (5 entities) → 1 LLM call @ 15/batch
- Context extraction: ~1 second for full transcript parsing
- Priority scoring: < 0.1 seconds
- **Total enrichment time: 2-5 seconds for typical transcript**

**Warning signs:**
- Enrichment takes >30 seconds for 50-entity transcript
- Multiple LLM calls per entity

## Code Examples

Verified patterns from research and existing codebase:

### Extract Transcript Context Windows

```python
# Source: Adapted from existing SRT parsing patterns in tools/srt_entities.py
import re

def extract_entity_context(srt_cues: list, entity_occurrences: list,
                          window_words: int = 125) -> str:
    """Extract context for entity from its occurrences.

    Args:
        srt_cues: List of parsed SRT cues from parse_srt()
        entity_occurrences: List of {"timecode": "00:01:23,456", "cue_idx": 42}
        window_words: Target words per context window (default ~paragraph)

    Returns:
        Merged context string with deduplicated overlaps
    """
    contexts = []

    for occur in entity_occurrences:
        cue_idx = occur["cue_idx"]
        # Find cue by index (cue.index is 1-based in SRT)
        cue = next((c for c in srt_cues if c.index == cue_idx), None)
        if not cue:
            continue

        # Extract surrounding cues (simple window: N cues before/after)
        # More sophisticated: word-count-based window
        window_size = 3  # 3 cues before/after ≈ 100-150 words
        start_idx = max(0, cue_idx - window_size - 1)
        end_idx = min(len(srt_cues), cue_idx + window_size)

        window_cues = srt_cues[start_idx:end_idx]
        context_text = " ".join(c.text for c in window_cues)

        # Clean up: collapse whitespace
        context_text = re.sub(r'\s+', ' ', context_text).strip()

        contexts.append(context_text)

    # Simple deduplication: join with separator
    # Advanced: detect overlaps (future improvement)
    return " [...] ".join(contexts)
```

### Calculate Priority Scores

```python
# Source: Based on Phase 1 CONTEXT decisions and diminishing returns research
from typing import Dict, Any

TYPE_WEIGHTS = {
    "people": 1.0,
    "events": 0.9,
    "organizations": 0.7,
    "concepts": 0.6,
    "places": 0.3
}

def calculate_entity_priority(entity: Dict[str, Any],
                              transcript_duration_seconds: float) -> float:
    """Calculate priority score for entity.

    Args:
        entity: Entity dict with entity_type, occurrences[]
        transcript_duration_seconds: Total transcript length

    Returns:
        Priority score 0.0-1.2
    """
    entity_type = entity.get("entity_type", "concepts")
    occurrences = entity.get("occurrences", [])

    # Base weight from type
    base_weight = TYPE_WEIGHTS.get(entity_type, 0.5)

    # Mention count multiplier (diminishing returns)
    mention_count = len(occurrences)
    if mention_count == 1:
        mention_mult = 1.0
    elif mention_count == 2:
        mention_mult = 1.3
    elif mention_count == 3:
        mention_mult = 1.5
    else:  # 4+
        mention_mult = 1.6

    # Position multiplier (first 20% boost)
    first_timecode = occurrences[0]["timecode"] if occurrences else "00:00:00,000"
    first_seconds = srt_time_to_seconds(first_timecode)
    position_pct = first_seconds / max(transcript_duration_seconds, 1.0)
    position_mult = 1.1 if position_pct <= 0.20 else 1.0

    # Calculate final score (capped at 1.2)
    score = base_weight * mention_mult * position_mult
    return min(score, 1.2)

def srt_time_to_seconds(timecode: str) -> float:
    """Convert SRT timecode 'HH:MM:SS,mmm' to seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', timecode)
    if not match:
        return 0.0
    h, m, s, ms = map(int, match.groups())
    return h * 3600 + m * 60 + s + ms / 1000.0
```

### Batch Entity Processing with Resilience

```python
# Source: Python 3.12+ itertools.batched() pattern
from itertools import batched  # Python 3.12+
from typing import List, Dict, Any

def enrich_entities_with_llm(entities: List[Dict[str, Any]],
                             llm_client, batch_size: int = 15) -> List[Dict[str, Any]]:
    """Enrich entities in batches with partial failure handling.

    Args:
        entities: List of entity dicts to enrich
        llm_client: LLM client with classify_type_batch() method
        batch_size: Entities per batch (default 15)

    Returns:
        Enriched entities list (same order as input)
    """
    enriched = []

    for batch in batched(entities, batch_size):
        try:
            # Batch LLM call for type classification
            batch_list = list(batch)  # batched() returns tuple
            classifications = llm_client.classify_type_batch(batch_list)

            # Merge classifications into entities
            for entity, classification in zip(batch_list, classifications):
                entity["entity_type"] = classification["type"]
                entity["enrichment_status"] = "success"
                enriched.append(entity)

        except Exception as batch_error:
            # Batch failed: fallback to individual processing
            print(f"Batch failed, retrying individually: {batch_error}")

            for entity in batch:
                try:
                    classification = llm_client.classify_type_single(entity)
                    entity["entity_type"] = classification["type"]
                    entity["enrichment_status"] = "success"
                except Exception as entity_error:
                    # Mark as failed, keep original type
                    entity["enrichment_status"] = "failed"
                    print(f"Entity enrichment failed: {entity.get('name')}: {entity_error}")

                enriched.append(entity)

    return enriched

# For Python 3.11 or earlier: fallback batched() implementation
def batched(iterable, n):
    """Batch data into tuples of length n. Last batch may be shorter."""
    from itertools import islice
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch
```

### Atomic JSON Checkpoint Write

```python
# Source: Atomic write pattern from research + existing codebase patterns
import json
import os
from pathlib import Path
from typing import Dict, Any

def write_checkpoint_atomic(data: Dict[str, Any], checkpoint_path: Path) -> None:
    """Write JSON checkpoint atomically with backup.

    Args:
        data: Dictionary to serialize as JSON
        checkpoint_path: Target file path (e.g., enriched_entities.json)
    """
    # Create backup if file exists
    if checkpoint_path.exists():
        backup_path = checkpoint_path.with_suffix('.bak')
        checkpoint_path.rename(backup_path)

    # Write to temp file
    temp_path = checkpoint_path.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Atomic rename (POSIX guarantees atomicity)
        temp_path.rename(checkpoint_path)

        # Success: remove backup
        backup_path = checkpoint_path.with_suffix('.bak')
        if backup_path.exists():
            backup_path.unlink()

    except Exception as e:
        # Restore from backup if exists
        backup_path = checkpoint_path.with_suffix('.bak')
        if backup_path.exists():
            backup_path.rename(checkpoint_path)

        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()

        raise RuntimeError(f"Checkpoint write failed: {e}") from e
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual batching loops | itertools.batched() | Python 3.12 (2023) | Cleaner code, memory-efficient |
| json module | orjson/ujson for performance | 2024-2025 | 2-5x faster JSON serialization (not needed for this project) |
| Separate validation libs | Pydantic v2 with type hints | 2023 | Built-in validation, but overkill for simple schemas |
| Custom diminishing returns | Standard formulas (1-e^-ax, power functions) | Always | Avoid reinventing math |
| Sequential LLM calls | Batch API calls | 2024-2025 (GPT-4 Turbo batching) | 50-80% latency reduction |

**Deprecated/outdated:**
- **Python <3.12 without itertools.batched()**: Use fallback implementation, but 3.12+ is recommended
- **pysrt library**: Existing parse_srt() handles more formats, no external dependency needed
- **Complex ML scoring models**: Phase 1 uses simple formulas; ML overkill for priority scoring

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal batch size for LLM classification**
   - What we know: 10-20 range recommended, trade-off between latency and failure isolation
   - What's unclear: Specific model rate limits (OpenAI vs Ollama differ)
   - Recommendation: Start with 15, make configurable flag --enrich-batch-size

2. **Context window exact word count vs cue count**
   - What we know: ~100-150 words is "paragraph-level", roughly 3-5 SRT cues
   - What's unclear: Should we count words exactly or use cue-based windows?
   - Recommendation: Use cue-based (simpler), verify in testing that context length reasonable

3. **LLM type classification prompt design**
   - What we know: Needs entity name + transcript context, return one of 5 types
   - What's unclear: Best prompt format, few-shot examples needed?
   - Recommendation: Follow existing prompt pattern in srt_entities.py, adapt for type classification

4. **Transcript duration calculation when SRT has gaps**
   - What we know: Last cue end time = total duration
   - What's unclear: What if transcript has large gaps (30+ min silence)?
   - Recommendation: Use last cue end time (simple), document assumption

## Sources

### Primary (HIGH confidence)

- [Python 3.13 Standard Library](https://docs.python.org/3/library/) - itertools, json, re modules
- [Pydantic Documentation](https://docs.pydantic.dev/) - Data validation patterns (optional for this phase)
- Existing codebase in tools/ - SRT parsing, entity tracking, checkpoint patterns

### Secondary (MEDIUM confidence)

- [Large Scale Batch Processing with Ollama](https://robert-mcdermott.medium.com/large-scale-batch-processing-with-ollama-1e180533fb8a) - Batch processing patterns
- [Crash-safe JSON at scale: atomic writes + recovery without a DB](https://dev.to/constanta/crash-safe-json-at-scale-atomic-writes-recovery-without-a-db-3aic) - Atomic write patterns
- [Python 3.12+ itertools.batched()](https://docs.python.org/3/library/itertools.html#itertools.batched) - Official batching documentation
- [Crawl4AI LLM Strategies](https://docs.crawl4ai.com/extraction/llm-strategies/) - Chunk overlap strategies
- [Improving LLMs for Clinical NER via Prompt Engineering](https://academic.oup.com/jamia/article/31/9/1812/7590607) - Entity classification prompt patterns
- [How to Build Modern Data Pipelines in 2026](https://www.alation.com/blog/building-data-pipelines/) - Pipeline checkpoint and failure recovery patterns
- [Effective Python Techniques for Chunking](https://sqlpey.com/python/effective-python-techniques-for-chunking/) - Batching and grouping patterns
- [Media Effect Estimation with PyMC: Diminishing Returns](https://juanitorduz.github.io/pymc_mmm/) - Diminishing returns curve examples
- [text-dedup GitHub](https://github.com/ChenghaoMou/text-dedup) - Text deduplication approaches

### Tertiary (LOW confidence)

- [pysrt · PyPI](https://pypi.org/project/pysrt/) - External SRT parser (not needed, existing parser better)
- Various web search results on word counting, percentage calculations - Basic Python patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Existing codebase patterns clear, minimal dependencies
- Architecture: HIGH - Checkpoint pattern well-established, enrichment fits naturally between stages
- Pitfalls: MEDIUM - Based on research and domain knowledge, but not all verified in practice

**Research date:** 2026-01-25
**Valid until:** 2026-03-01 (30 days - stable domain, unlikely to change)

**Assumptions:**
- Python 3.13 is target environment (confirmed via existing codebase)
- LLM provider supports batch requests (true for OpenAI, Ollama can simulate)
- JSON checkpoints remain under 10MB (typical transcripts have <200 entities)
- SRT format continues to match existing parse_srt() patterns
