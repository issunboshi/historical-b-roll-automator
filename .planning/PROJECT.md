# B-Roll Automater - Wikipedia Image Improvements

## What This Is

A b-roll automation pipeline that extracts named entities from video transcripts and downloads representative Wikipedia images for use as picture-in-picture overlays in DaVinci Resolve. This milestone focuses on improving the Wikipedia image download stage to find more accurate, contextually-correct images with less manual intervention.

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

### Active

<!-- Current scope. Building toward these. -->

- [ ] LLM-generated search strategies — ask LLM for multiple Wikipedia search queries based on entity + story context
- [ ] Context-aware disambiguation — when multiple Wikipedia results exist, LLM picks the one matching story context
- [ ] Entity-type prioritization — always find images for people/events, places less aggressively (every X minutes)
- [ ] Image variety — when multiple good images exist and entity mentioned multiple times, use different images at different mentions
- [ ] Higher API throughput — investigate/implement higher Wikipedia rate limits (willing to pay if service exists)
- [ ] Match quality tracking — record which entities got good matches vs. poor/no matches for review

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Image quality analysis (resolution, composition) — images are shown small as PiP, fine details don't matter
- Manual image curation UI — this is a CLI tool, not a GUI application
- Non-Wikipedia image sources — Wikipedia provides licensing metadata we need; other sources complicate rights
- Real-time processing — batch processing is sufficient for the workflow

## Context

**Current pipeline stages:**
1. Entity extraction (tools/srt_entities.py) — parses SRT, calls LLM per cue
2. Image download (tools/download_entities.py + wikipedia_image_downloader.py) — maps entities to Wikipedia, downloads images
3. Timeline generation (generate_broll_xml.py) — creates FCP 7 XML with clip placements

**The problem:** Stage 2 currently does a naive Wikipedia search using the entity name directly. This fails when:
- Ambiguous names exist (William Dawes: Australian colonist vs American revolutionary)
- Entity name differs from Wikipedia article title
- Multiple valid Wikipedia articles exist for the same concept

**Recent improvement:** Added canonical name resolution in entity extraction (aliases merge to canonical form). This helps but doesn't solve disambiguation.

**Image usage context:** Images appear as small picture-in-picture overlays. They need to be clearly identifiable as the entity but fine details don't matter.

## Constraints

- **Tech stack**: Python 3.13+, existing architecture — maintain compatibility with current pipeline
- **LLM**: Flexible — OpenAI, Ollama, or other providers acceptable
- **Budget**: Flexible within reason — willing to pay for better API access if available
- **Wikipedia API**: Must respect rate limits; investigate if paid/faster access exists

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use LLM for search strategy generation | LLM already has story context from extraction; can suggest contextual queries | — Pending |
| Use LLM for disambiguation | LLM can compare Wikipedia article summaries against transcript context | — Pending |
| Prioritize people/events over places | People/events are visually distinctive; places can be repetitive | — Pending |

---
*Last updated: 2026-01-25 after initialization*
