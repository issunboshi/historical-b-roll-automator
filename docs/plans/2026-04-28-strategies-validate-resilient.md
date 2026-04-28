# Resilient Wikipedia Validation in `generate_search_strategies` — Implementation Plan

**Goal:** Stop a single bad Wikipedia API response from killing the entire `strategies` pipeline step (and forfeiting the upstream LLM spend).

**Symptom we're fixing:**
```
Strategy generation complete: 60 generated, 0 failed
Error: Failed to validate strategies: Expecting value: line 1 column 1 (char 0)
```

The validator calls `wikipediaapi.Wikipedia.page(title).exists()`, which internally does
an unguarded `r.json()`. When Wikipedia's edge returns an empty body or HTML error page
(common during transient CDN/gateway hiccups), `requests.Response.json()` raises
`json.JSONDecodeError`, bubbles up through `validate_strategies()`, and aborts the script
with exit code 1. The orchestrator then refuses to mark the step complete, so `--resume`
re-runs all 9 LLM batches before hitting the same Wikipedia failure on the next attempt.

**Status:** implemented 2026-04-28.

## Design choices

### Per-title error policy: **Policy A (optimistic)**
On `validator.validate()` exception, treat the title as `valid=True, canonical=None` and
keep the query in the validated set. Rationale: the next pipeline step (`download`) does
its own MediaWiki title lookup with retries, so a soft validation failure is recoverable
downstream. The pessimistic alternative would silently shrink the query pool every time
the API hiccups.

### Two-phase atomic write
The strategies file is written to disk **before** validation runs, using the LLM-generated
strategies. Validation then mutates the in-memory dict and the file is rewritten with the
validated form. If validation crashes catastrophically (caught at the top level), the
unvalidated file is already on disk, the script exits 0, and `--resume` skips the
expensive LLM step.

## Changes

### `tools/generate_search_strategies.py`
1. `validate_strategies()` — wrap each `validator.validate()` call in try/except. On
   exception: increment a `validation_errors` counter, log a warning with title and
   `type(exc).__name__: exc`, and synthesize `result = {"exists": True,
   "canonical_title": None, "canonical_url": None}`. End-of-function summary now
   includes the validation-error count.
2. Refactor the existing inline `mkstemp + os.replace` write into a private
   `_write_strategies_atomic(out_path, result)` helper.
3. In `main()`, call `_write_strategies_atomic` *before* validation. After validation,
   call it again with the validated result. If `validate_strategies()` raises (which is
   now rare since per-title errors are caught), log a warning and continue with exit 0
   — the unvalidated file is already persisted.

### `tests/test_generate_search_strategies.py` (new)
- `test_validate_strategies_swallows_per_title_errors` — patch
  `WikipediaValidator.validate` to raise on a specific query; assert validation
  completes, the failing query is kept (Policy A), and other queries validate normally.
- `test_validate_strategies_logs_error_count` — assert the warning summary mentions the
  failure count.

### `CLAUDE.md`
Add a brief note under a new "Strategy Validation" subsection explaining Policy A and
the two-phase write, so this design isn't re-litigated next time.

## Out of scope
- No CLI/argparse changes — same flags, same outputs.
- No README updates — no user-visible behavior change beyond resilience.
- Not switching off `wikipediaapi`. The library is fine for the happy path; we just
  refuse to let it take the whole step down.
