# Phase 1: Enrichment Foundation - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Add enrichment infrastructure that augments entity metadata with priority scores and transcript context before download attempts. This creates a new pipeline stage between extraction and download. Filtering entities based on priority (skipping low-value ones) is Phase 3 — this phase only scores them.

</domain>

<decisions>
## Implementation Decisions

### Priority Scoring Formula
- **Type weights:** People highest, Events/Dates third (dates need video context to avoid random images), then Organizations, Concepts, Places in descending order
- **Mention count:** Diminishing returns curve — first few mentions matter most (1 mention = 1.0x, 2 = 1.3x, 3 = 1.5x, 4+ = 1.6x)
- **Position weight:** Mild early boost — first 20% of transcript = 1.1x, rest = 1.0x
- **Score cap:** Allow up to 1.2 — exceptional entities (high type + many mentions + early) can exceed 1.0

### Context Extraction
- **Window size:** Paragraph-level (~100-150 words surrounding context per mention)
- **Multi-mention handling:** All mentions merged into one combined context blob
- **Speaker attribution:** Text only — strip speaker labels, just the words matter
- **Overlap handling:** Deduplicate overlapping windows when mentions are close together

### Entity Type Classification
- **Source:** Hybrid — use extraction type if confident, otherwise enrich with LLM
- **Type set:** Core set — Person, Place, Organization, Event, Concept (5 types)
- **Dates/Eras:** Classify as Event type (e.g., '1942' and 'World War II' both become Event)
- **Ambiguous fallback:** Always LLM classify when extraction type is ambiguous (e.g., 'MISC')

### Enrichment Timing
- **Batching:** Chunked batches — groups of 10-20 entities per LLM call (balance of speed and resilience)
- **Checkpoint:** Separate file — create enriched_entities.json, keeps original extraction untouched
- **Failure handling:** Continue with partial — use enriched entities, mark failures as 'enrichment_failed'
- **Command access:** Pipeline only — runs as part of `broll.py pipeline`, not a separate standalone command

### Claude's Discretion
- Exact diminishing returns formula (as long as it follows the pattern)
- Chunk size within 10-20 range based on typical entity counts
- Specific deduplication algorithm for overlapping context windows
- LLM prompt design for type classification

</decisions>

<specifics>
## Specific Ideas

- Dates need to reference the general context of the video so images aren't random (e.g., "1942" in a WWII documentary should pull WWII-related images, not generic "1942" images)
- People should always be highest priority — they're what viewers connect with

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-enrichment-foundation*
*Context gathered: 2026-01-25*
