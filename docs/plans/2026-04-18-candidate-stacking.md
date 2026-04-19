# Candidate Stacking

**Status:** In Progress
**Date:** 2026-04-18
**Branch:** `feature/candidate-stacking`

## Purpose

Let editors decide the winning image per entity *in the NLE* rather than
trusting the round-robin. At each selected occurrence, place every
candidate image for that entity on the timeline, stacked on consecutive
tracks at the same frame. The editor disables/solos tracks to pick the
winner, then flattens.

## CLI

```
--candidates N     Images per occurrence (default: 1 = current behaviour).
                   N >= 2 stacks N images on consecutive tracks.
                   N = 0 or "all" stacks every available candidate.
```

Available on both `pipeline` and `xml` subcommands.

## Behaviour

- **N = 1** (default) — unchanged. One image per occurrence, round-robin
  through the pool over the entity's multiple occurrences.
- **N >= 2** — each occurrence expands into N clips at the same frame on
  tracks V(base)..V(base+N-1). Later occurrences of the same (or other)
  entities go on the next free time slot, same gap logic as today, but
  *track allocation reserves N consecutive tracks at once*.
- **N = 0 or "all"** — N is set per-entity to `len(filtered_images)` so
  every candidate shows up. Different entities produce stacks of different
  heights; track count auto-expands to the max stack size.

### Image ordering within a stack

Top track (highest V) = highest-ranked image (index 0 in the pool).
Resolve shows highest track on top when multiple are enabled, so the
editor sees the "best guess" by default; lower tracks are alternates.

### Interaction with --coverage

When `--candidates > 1`:
- **Stretch** still fires (short gaps extend the top-of-stack).
- **Recycle filler** is suppressed. Stacking fillers adds noise (an
  unlabelled tangent with 4 layers) rather than editorial choice.
- A one-line notice prints so the behaviour isn't surprising.

### Track arithmetic

- Default `--tracks` is 4. With `--candidates 4`, exactly one stack fits;
  any overlapping occurrence is pushed to a later time slot via the
  existing "all tracks busy" branch in `generate_xml.py`.
- With `--candidates all`, we auto-grow `tracks` to the max stack size if
  the user hasn't overridden `--tracks`. A user-supplied `--tracks`
  overrides and truncates per-entity stacks if needed.

## Implementation

### `tools/generate_xml.py`

- New arg `--candidates` parsed as int OR `"all"`.
- In the clip-building loop (around line 567), instead of picking
  `filtered_images[idx % len]`, emit one clip per image in the stack
  with a new field `stack_offset` (0 = top, 1..N-1 = below).
- In the track-assignment loop, group clips by `(frame, entity,
  occurrence_index)` into *placement groups*. A group claims N consecutive
  tracks at once; if no N-wide slot exists at the clip's frame, the group
  is deferred (same pattern as existing "all tracks busy").
- `run_coverage_pass` takes a new `allow_recycle: bool` argument; set
  false when stacking.

### `broll.py`

- Add `--candidates` to `p_pipeline` and `p_xml`.
- `cmd_xml` forwards the flag when set.
- `cmd_pipeline`'s `xml_args` Namespace carries `candidates`.

## Testing

- `python -m py_compile`
- `--help` for both subcommands
- Inline behavioural test: 1 occurrence × 3 images at N=3 → 3 clips at the
  same frame on V2/V3/V4, ordered best-to-bottom-track.
- Stack collision: two entities with overlapping occurrences at N=3 on
  `--tracks 4` → second one deferred.

## Out of Scope

- Per-entity override for N (e.g. "only stack for people, not places").
- Visual label/disabler text on the lower tracks.
