# B-Roll Quality Improvements — Accuracy, Relevance, Deduplication, Frequency Capping

**Date:** 2026-02-10
**Status:** Completed
**Archived:** 2026-02-10

## Context

Running the pipeline on a 13-minute video about the 1857 Indian Rebellion produced unusable output:
- "United Kingdom" (26 mentions) and "India" (16 mentions) each got a clip at every mention, cycling through generic Wikipedia images
- Bad disambiguations: "Ernest Jones" -> wrong person (psychoanalyst born 1879, not the 1850s Chartist)
- Duplicate entities from transcription variants: "Pandey"/"Mangal Pandey"/"Mandel Pandey" as 3 separate entries

## What Was Built

### Phase 1: Frequency Capping (generate_xml.py)
- `calculate_placement_budgets()` — budget per entity based on priority and pervasiveness
- `select_occurrences()` — smart placement selection (first, last, evenly spaced)
- New CLI args: `--max-placements`, `--pervasive-max`

### Phase 2: Transcript Summary (tools/summarize_transcript.py — new)
- Single LLM call produces topic, era, era_year_range, pervasive_entities, entity_clusters
- Transcript sampling (~35 cues) to keep token cost low
- Claude structured outputs with Pydantic models

### Phase 3: Entity Merging (tools/merge_entities.py — new)
- Cluster-based merging from LLM-identified clusters
- Fuzzy fallback using difflib.SequenceMatcher (threshold 0.85)
- Deduplication by timecode, union of aliases, max priority

### Phase 4: Context-Aware Search & Disambiguation
- **generate_search_strategies.py** — era context and pervasive entity redirection in prompts
- **src/core/disambiguation.py** — chronological fit checks in disambiguation prompt
- **disambiguate_entities.py** — loads summary, passes era through
- **download_wikipedia_images.py** — era-aware image reordering
- **download_entities.py** — passes era_year_range downstream

### Phase 5: Pipeline Wiring (broll.py)
- New pipeline steps: `summarize`, `merge-entities`
- New CLI args: `--era`, `--pervasive-entities`, `--max-placements`, `--pervasive-max`, `--skip-summary`
- Smart file path logic: prefers merged > enriched entities

## Files Modified/Created

| File | Action |
|------|--------|
| `tools/generate_xml.py` | Modified: frequency capping |
| `tools/summarize_transcript.py` | Created |
| `tools/merge_entities.py` | Created |
| `tools/generate_search_strategies.py` | Modified: era + pervasive context |
| `src/core/disambiguation.py` | Modified: era param + chronological fit |
| `tools/disambiguate_entities.py` | Modified: load summary, pass era |
| `tools/download_wikipedia_images.py` | Modified: era-aware reordering |
| `tools/download_entities.py` | Modified: pass era_year_range |
| `broll.py` | Modified: new steps, CLI args, file paths |
