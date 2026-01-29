# Phase 5: Image Variety & Quality Filtering - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Entities mentioned multiple times use different images at each mention, and timeline generation filters by match quality. This phase adds image rotation logic and quality-based filtering to the existing pipeline. Image sourcing changes (e.g., alternative sources beyond Wikipedia) are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Image Rotation Strategy
- Quality-ranked assignment: best image for first mention, second-best for next, etc.
- When images exhausted: cycle back to best image (mention 4 gets Image 1 if only 3 images)
- Repeats only at exhaustion: avoid same image for consecutive mentions until all images used
- Quality ranking method: Claude's discretion based on available metadata

### Image Count Rules
- Threshold for extra images: 3+ mentions triggers fetching up to 5 images (instead of 3)
- Single-mention entities: keep current behavior (3 images for fallback options)
- Scaling with mentions: Claude's discretion on whether to scale or use fixed count
- Insufficient images: use what's available, rotation will cycle back when needed

### Quality Threshold Behavior
- Below threshold: exclude completely from timeline (hard cutoff, no placeholders)
- Default threshold: high (strict) — only include high-quality matches by default
- Excluded entity logging: both console output and separate file for later review
- Confidence mapping: Claude's discretion on mapping Phase 4 scores to quality levels

### Claude's Discretion
- How to determine image quality ranking (resolution, Wikipedia order, or hybrid)
- Whether image count scales with mention count or stays fixed at 5
- Exact confidence-to-quality-level mapping from Phase 4

</decisions>

<specifics>
## Specific Ideas

- The quality filtering should be strict by default because it's better to show fewer, correct images than many questionable ones
- Logging excluded entities is important for debugging and understanding what's being filtered out

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-image-variety-quality*
*Context gathered: 2026-01-29*
