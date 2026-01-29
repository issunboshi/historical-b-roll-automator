# Phase 3: Priority-Based Filtering - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Skip downloading images for low-value entities based on priority scores, reducing wasted Wikipedia API calls. Filtering happens at download stage using priority scores computed in Phase 1. Does not modify enrichment — all entities still get scored and contextualized.

</domain>

<decisions>
## Implementation Decisions

### Threshold values
- Default minimum priority threshold: **0.5** (balanced — skip bottom ~40%)
- Graduated filtering with warning zone:
  - Below 0.3 = skip
  - 0.3–0.5 = warn but download
  - Above 0.5 = download normally
- Setting `--min-priority 0` disables filtering entirely (no separate --no-filter flag needed)

### Entity type rules
- **People always download** — never skip regardless of priority score
- **Events always download** — never skip regardless of priority score
- **Places**: Can override threshold if they meet 2+ mentions OR early mention (first 10%)
- **Concepts**: Higher threshold of 0.7 (harder to visualize — only include high-priority ones)

### Transparency logging
- Per-entity skip logs + summary at end
- Per-entity logs require `-v/--verbose` flag; summary always shown
- Skipped entities recorded in output JSON (`skipped` array)
- Full information per skip: name, type, priority, mentions, reason

### Override behavior
- No per-entity overrides — use `--min-priority 0` to include everything
- Filtering applies at **download stage only** — enriched JSON contains all entities
- Re-runs skip already-downloaded entities (checkpoint-aware)

### Claude's Discretion
- CLI flag structure (single --min-priority or separate --min and --warn)
- Dry-run mode implementation (if useful for debugging)
- Exact log message formatting

</decisions>

<specifics>
## Specific Ideas

- Warning zone (0.3–0.5) entities should be visually distinguishable in verbose output
- The skip reason should be human-readable: "place with 1 mention, not in first 10%"

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-priority-based-filtering*
*Context gathered: 2026-01-29*
