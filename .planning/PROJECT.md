# B-Roll Automater

## What This Is

A b-roll automation pipeline that extracts named entities from video transcripts and downloads representative Wikipedia images for use as picture-in-picture overlays in DaVinci Resolve. The v1 milestone added intelligent, context-aware image matching using LLM-generated search strategies and disambiguation with confidence scoring.

## Core Value

Reliably find the RIGHT image for each entity — the one that matches the story context — without requiring manual fixes or additional searching.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Extract entities (people, places, events, concepts) from SRT transcripts using LLM — existing
- ✓ Canonical name resolution with alias merging (Obama → Barack Obama) — existing
- ✓ Download Wikipedia images with parallel execution — existing
- ✓ License classification (public domain, CC-BY, etc.) — existing
- ✓ Generate FCP 7 XML timeline for DaVinci Resolve import — existing
- ✓ Configuration via YAML/environment/CLI flags — existing
- ✓ Support for OpenAI and Ollama LLMs — existing
- ✓ LLM-generated search strategies — ask LLM for multiple Wikipedia search queries based on entity + story context — v1
- ✓ Context-aware disambiguation — when multiple Wikipedia results exist, LLM picks the one matching story context — v1
- ✓ Entity-type prioritization — always find images for people/events, places less aggressively — v1
- ✓ Image variety — when multiple good images exist and entity mentioned multiple times, use different images at different mentions — v1
- ✓ Match quality tracking — record which entities got good matches vs. poor/no matches for review — v1

### Active

<!-- Current scope. Building toward these. -->

(None — fresh requirements defined in next milestone via `/gsd:new-milestone`)

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Image quality analysis (resolution, composition) — images are shown small as PiP, fine details don't matter
- Manual image curation UI — this is a CLI tool, not a GUI application
- Non-Wikipedia image sources — Wikipedia provides licensing metadata we need; other sources complicate rights
- Real-time processing — batch processing is sufficient for the workflow

## Context

**Current state (v1 shipped):**
- 5-step pipeline: extract → enrich → strategies → download → xml
- ~4,500 lines of Python (core pipeline tools)
- Tech stack: Python 3.13+, Claude (Anthropic), OpenAI, Wikipedia API
- Key modules: enrich_entities.py, generate_search_strategies.py, download_entities.py, disambiguation.py, generate_broll_xml.py

**v1 delivered:**
- Priority scoring (type + mentions + position) for entity filtering
- LLM-generated Wikipedia search queries (2-3 per entity)
- Context-aware disambiguation with confidence scoring (0-10)
- Confidence routing: auto-accept (7+), flag for review (4-6), skip (0-3)
- Image variety through round-robin rotation for multi-mention entities
- Quality-based timeline filtering via --min-match-quality flag

**Expected match rate:** ~85-90% (up from ~60% baseline)

**v2 candidates (from REQUIREMENTS.md):**
- Temporal context extraction (year, decade, era)
- Geographic context extraction (location keywords)
- Alias variation fallbacks
- Entity-type-specific disambiguation strategies
- Disambiguation result caching

## Constraints

- **Tech stack**: Python 3.13+, existing architecture — maintain compatibility with current pipeline
- **LLM**: Flexible — OpenAI, Ollama, or other providers acceptable
- **Budget**: Flexible within reason — willing to pay for better API access if available
- **Wikipedia API**: Must respect rate limits; no paid/faster access available

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use LLM for search strategy generation | LLM already has story context from extraction; can suggest contextual queries | ✓ Good — 85-90% match rate |
| Use LLM for disambiguation | LLM can compare Wikipedia article summaries against transcript context | ✓ Good — confidence scoring works well |
| Prioritize people/events over places | People/events are visually distinctive; places can be repetitive | ✓ Good — reduces noise |
| Claude structured outputs for JSON | Eliminates 10-30% retry attempts from malformed JSON | ✓ Good — reliable extraction |
| Batch size 7 entities per LLM call | Research-backed balance between API efficiency and context quality | ✓ Good — acceptable latency |
| 7-day cache TTL for Wikipedia validation | Balances freshness vs API load | ✓ Good — rarely stale |
| Confidence routing (7+/4-6/0-3) | Clear thresholds for auto-accept/flag/skip | ✓ Good — reduces manual review |
| Default quality threshold: high | Only confident matches in timeline by default | ✓ Good — clean timelines |

---
*Last updated: 2026-01-29 after v1 milestone*
