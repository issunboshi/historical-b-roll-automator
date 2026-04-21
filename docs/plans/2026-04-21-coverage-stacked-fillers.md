# Coverage Stacked Fillers

**Status:** Implemented
**Date:** 2026-04-21
**Branch:** `feature/coverage-stacked-fillers`

## Purpose

Make `--coverage` and `--candidates` compose correctly. Previously, activating
candidate stacking (`--candidates all` or `N>=2`) silently suppressed the
recycle-fill half of `--coverage`, because the original design considered a
single-image filler visually incongruous next to multi-layer stacked primary
placements. In practice this meant users running

```
broll.py pipeline --coverage 100 --candidates all ...
```

got almost no extra coverage: only the stretch phase ran, and stretch only
extends clips across gaps shorter than `--stretch-threshold` (default 5s).

This change emits gap fillers *as stacks themselves* — one filler entity's
candidate images stacked across consecutive tracks at the gap position — so
the aesthetic is preserved while still achieving coverage.

## Behaviour

- **`--candidates 1` (default)** — unchanged. Flat per-track recycle fillers
  as before.
- **`--candidates N` (N>=2) with `--coverage`** — gap fillers stack N images
  from a single filler entity across tracks V(base)..V(base+N-1). Short gaps
  still stretch per-track as before.
- **`--candidates all` with `--coverage`** — each filler stacks every
  available image for that entity (capped at `--tracks`). Different filler
  entities can produce different stack heights.

### Filler image ordering within a stack

Top track (highest V) = highest-ranked image (index 0 in the entity's pool).
Matches the primary stacking convention so the default view still shows the
"best guess" image per filler.

### Track occupancy & collisions

Stacked fillers are emitted based on gaps on the *base track* (V2). However,
non-base tracks may have been used by *taller* primary stacks elsewhere,
leaving their clips still running inside what looks like a base-track gap.
The emitter checks each candidate time slot against every track the stack
would occupy and skips the slot if any of those tracks is busy (respecting
`--gap`). This avoids XML-level overlaps without requiring a global
occupancy rebuild.

## CLI

No new flags. Existing `--coverage`, `--candidates`, `--stretch-threshold`
now compose correctly.

## Implementation

### `tools/generate_xml.py`

- **New** `build_filler_entity_pool(qualified_entities, pervasive_entities,
  allow_non_pd) -> list[(name, [imgs])]` — entity-grouped pool for stacked
  recycling. Same ordering as the existing flat pool (pervasive first, then
  priority-desc); filters out entities with no disk-present images.
- **Kept** `build_filler_image_pool(...)` — now a thin wrapper that flattens
  the entity pool. The flat rotation remains the default for `--candidates 1`.
- **New** `filler_stack_size(entity_images, args_candidates, max_tracks) -> int`
  — user-tuneable taste function deciding stack height per filler entity.
  Default policy: permissive (short stacks allowed). Strict alternative
  (skip entities with fewer images than target height) documented in the
  docstring.
- **New** `_emit_stacked_fillers_in_gap(...)` — walks one base-track gap,
  rotates through `entity_pool`, and emits `stack_size` placements per filler
  slot across consecutive tracks. Skips time slots with per-track collisions.
- **New helpers** `_gaps_for_track(...)` and `_track_free(...)` — extracted
  from the existing pass so both flat and stacked paths can reuse them.
- **Refactored** `run_coverage_pass(...)` — now accepts `stack_height`,
  `entity_pool`, `args_candidates`. When `stack_height >= 2` and an
  `entity_pool` is provided, runs stretch per-track first (mutates), then a
  base-track-only stacked recycle phase. Otherwise falls through to the
  legacy per-track flat path.
- **`main()`** — removed the "Coverage recycle fillers disabled" suppression;
  computes `stack_height` from `args.candidates`, builds both pools, passes
  both to `run_coverage_pass`, and updates the log line to report the
  stacking mode.

### `broll.py`

No changes — `--candidates` and `--coverage` were already forwarded from the
`pipeline` and `xml` subcommands.

## Pipeline Integration

Runs as part of the existing `xml` step, in the same position as before.
Checkpointing is unaffected (no new pipeline steps).

## Data Requirements

Unchanged: `--srt` still required for duration calculation;
`transcript_summary.json` (auto-detected) still feeds the pervasive ordering.

## Out of Scope

- Per-filler-entity cooldown (same entity appearing in two adjacent stacks).
- Smart filler selection by surrounding narration topic.
- Strict "full stacks only" enforcement — left as a taste toggle in
  `filler_stack_size()`.

## Testing

- `python -m py_compile tools/generate_xml.py broll.py`
- `python broll.py xml --help`
- Unit-style smoke test: synthetic 4-track timeline with a single primary
  V2/V3/V4 stack at frames 0–120 and a 45-second gap → produces six
  alternating 3-high filler stacks rotating through two entities.
- Flat regression test: same setup with `--candidates 1` → 31 single-clip
  fillers across V2-V5 as before.
