# Full Coverage Mode

**Status:** In Progress
**Date:** 2026-04-18
**Branch:** `feature/full-coverage-mode`

## Purpose

Let faceless YouTube creators produce timelines where B-roll covers most of
the video — not just the moments where a named entity is mentioned. Existing
output is sparse by design (entities are frequency-capped to avoid repetition);
this mode inverts that trade-off for creators who need something on-screen at
all times.

## CLI

One new flag on both `pipeline` and `xml` subcommands:

```
--coverage <PCT>    Target timeline coverage as a percentage (0-100).
                    Default off (current sparse behaviour).
                    Example: --coverage 90  → fill gaps until ~90% of the
                    SRT duration is covered by B-roll.
```

When `--coverage` is set, the frequency caps (`--max-placements`,
`--pervasive-max`) are still honoured for the *primary* placement pass;
coverage is hit by a second *fill pass* that adds extra clips.

## Gap-filling strategy: hybrid stretch + recycle

For each gap on each track between the primary placements:

1. **Short gaps** (< `stretch_threshold`, default 5 s) — extend the previous
   clip's duration so it runs up to the next clip start (minus the configured
   `--gap`). No new media, just longer holds.
2. **Long gaps** (>= `stretch_threshold`) — insert one or more filler clips
   pulled from the entity image pool. Preference order:
   - Pervasive/background entities (identified from `transcript_summary.json`)
   - Highest-priority entities with unused images
   Each filler uses the standard `--duration` length, respecting `--gap`.

This is deliberately two-phase: the primary pass preserves the "right image
at the right time" placements; the fill pass just bulks up coverage.

## Implementation

### `tools/generate_xml.py`

- New `srt_duration_seconds(srt_path)` helper — reads the final cue's end
  time. Needed because current timeline length is derived from placements.
- New `fill_gap_hybrid(gap_start, gap_end, prev_placement, image_pool, args)`
  — **user-implemented strategy function**. Returns a list of new placements
  (or mutates the previous one's duration for stretch). This is the core
  taste decision and is left for the user.
- New `run_coverage_pass(placements, total_frames, image_pool, args)` —
  orchestrator that walks each track, calls `fill_gap_hybrid` per gap,
  collects new placements, and logs final coverage %.
- New CLI arg: `--coverage` (float). When None → current behaviour.

### `broll.py`

- Add `--coverage` to both `p_pipeline` and `p_xml` argparse blocks.
- `cmd_xml` forwards `--coverage` to the script when set.
- `cmd_pipeline`'s `xml_args` namespace includes `coverage`.
- `cmd_xml` also needs the SRT path (for duration); pass via new
  `--srt` arg on the `xml` subcommand (already available on `pipeline`).

## Pipeline Integration

The fill pass runs **after** the existing track-assignment loop in
`generate_xml.py:main()` and **before** `create_fcp_xml()`. No checkpoint
step change — it's part of the existing `xml` step.

## Data Requirements

- SRT path reachable from the `xml` step (new `--srt` argument).
- `transcript_summary.json` (already auto-detected) for pervasive-entity
  preference ordering in recycle mode.

## Out of Scope (for this iteration)

- Smart per-gap image selection based on narration topic (would need
  per-cue entity windowing — possible follow-up).
- Cross-fade transitions between stretched clips.
- Per-entity cooldown to avoid same image appearing twice in a short window
  (nice follow-up; current recycle order loosely avoids it).

## Testing

- `python -m py_compile tools/generate_xml.py broll.py`
- `python broll.py pipeline --help` / `python broll.py xml --help`
- Run `xml` step on an existing project directory with `--coverage 80` and
  verify the logged final coverage % is in range.
