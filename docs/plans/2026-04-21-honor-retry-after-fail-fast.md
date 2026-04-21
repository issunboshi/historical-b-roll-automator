# Honor Retry-After, Fail Fast on Rate Limits

**Status:** In Progress
**Date:** 2026-04-21
**Branch:** `feature/honor-retry-after-fail-fast`

## Purpose

The Wikimedia upload CDN (`upload.wikimedia.org`) sends `HTTP 429` with
`Retry-After: 60` for hot files when the pipeline runs parallel entities.
Today the downloader honors the full 60s **five times in a row** per image
(see `tools/download_wikipedia_images.py:1101-1113`), which means a single
rate-limited image stalls for ~5 minutes and still fails. With parallel
entities hammering the CDN, every image for an unlucky entity can time out
this way, causing consistent "all search terms failed" outcomes for entities
whose Wikipedia page (and title) are perfectly correct.

Concrete case: `Thomas Wentworth, 1st Earl of Strafford` — page resolves,
confidence-10 disambiguation, 12 file links found, every file 429'd.

## Change

### 1. `http_get_retry` — honor Retry-After **once**, then fail fast

- On the first `429`, honor `Retry-After` (capped at `_429_RETRY_AFTER_CAP_S`,
  default 10s; never waste >10s on a speculative retry).
- On the second `429` from the same request, raise a new
  `RateLimitedError(url, retry_after)` — no further retries, no jitter, no
  exponential backoff.
- 5xx retry path is **unchanged** (still up to `MAX_RETRIES` with
  `RETRY_BACKOFF_S` exponential backoff + jitter).

### 2. New distinct exit code from the downloader

- Add exit code `3` to `download_wikipedia_images.py` meaning "no images
  succeeded **and** at least one was rate-limited". `2` stays "no images and
  no rate-limit cause" (genuine failure — empty page, filtering, etc.).
- Track per-query `any_success` and `any_rate_limited` through the main
  loop; prefer `3` over `2` when deciding final exit.

### 3. `download_entities.py` — propagate `rate_limited` entity status

- Catch `subprocess.CalledProcessError` with `e.returncode == 3`.
- Set `payload["download_status"] = "rate_limited"` on the entity (in
  addition to the existing `"failed"` / `"no_images"` statuses).
- Print a one-line "rate-limited; eligible for `--retry-failed`" notice
  instead of the generic "Failed" message.

### 4. Extend `--retry-failed` to include `rate_limited`

- `--retry-failed` already selects entities with `download_status` in
  `{"failed", "no_images"}`; add `"rate_limited"` to the set so a second
  pass after the CDN cools picks them up naturally.

## Out of scope

- Adaptive concurrency (backing off `--parallel` / `--download-workers` on
  repeated 429s). Worth doing, but a separate change.
- Per-host rate limiter (upload.wikimedia.org vs en.wikipedia.org). The
  existing global `_RateLimiter` is process-local; pipeline-wide coordination
  is a bigger refactor.
- File-level retry queueing (re-enqueueing just the failed images rather
  than the whole entity). Would be nicer UX; not needed for the durable fix.

## Testing

- Unit test: mock a `requests.Session` whose first call returns `429` with
  `Retry-After: 1`, second call returns `200`. Assert `http_get_retry`
  returns the successful response and sleeps ~1s total (single honor).
- Unit test: mock a session returning `429` twice. Assert
  `RateLimitedError` is raised and the second sleep is not performed.
- Live repro on `Thomas Wentworth, 1st Earl of Strafford`: run download
  with the change; confirm exit code 3 on pure-429 runs and normal exit 0
  when at least one image lands.

## Rollback

Purely internal behavior change — no new CLI flags, no output format
shift. Revert the commit and behavior returns to 5×60s waits per image.
