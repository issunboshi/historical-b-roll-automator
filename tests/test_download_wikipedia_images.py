"""Tests for retry/rate-limit behaviour in tools/download_wikipedia_images.py.

Focus: http_get's fail-fast handling of HTTP 429. Previously the downloader
honored Retry-After five times per image (up to ~5 min of stalled retries
per hot file) which caused correct, high-confidence entities to be declared
failed. The durable fix honors Retry-After exactly once, then raises
RateLimitedError so the orchestrator can re-queue the entity later.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

# Make `tools/` importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import download_wikipedia_images as dwi  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = b""
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _fake_session(responses: list[_FakeResponse]) -> MagicMock:
    """Build a MagicMock session whose .get() returns the queued responses
    in order (one per call)."""
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = responses
    return session


def test_429_then_200_honors_retry_after_once(monkeypatch):
    """First 429 with Retry-After is honored (one sleep), then the retry
    returns 200 and http_get returns that response."""
    session = _fake_session([
        _FakeResponse(429, {"Retry-After": "1"}),
        _FakeResponse(200),
    ])
    slept: list[float] = []
    monkeypatch.setattr(dwi.time, "sleep", slept.append)

    resp = dwi.http_get(session, "https://example.invalid/file.png")

    assert resp.status_code == 200
    assert len(slept) == 1, "expected exactly one honored Retry-After wait"
    assert slept[0] == 1.0, f"expected to honor Retry-After=1s, slept {slept}"
    assert session.get.call_count == 2


def test_second_429_fails_fast_with_rate_limited_error(monkeypatch):
    """Two consecutive 429s: first honored, second raises RateLimitedError
    immediately with no further sleep."""
    session = _fake_session([
        _FakeResponse(429, {"Retry-After": "1"}),
        _FakeResponse(429, {"Retry-After": "60"}),
    ])
    slept: list[float] = []
    monkeypatch.setattr(dwi.time, "sleep", slept.append)

    with pytest.raises(dwi.RateLimitedError) as excinfo:
        dwi.http_get(session, "https://example.invalid/file.png")

    assert len(slept) == 1, "must not sleep again on the second 429"
    assert excinfo.value.retry_after == 60.0
    assert "example.invalid" in str(excinfo.value)
    assert session.get.call_count == 2


def test_retry_after_is_capped(monkeypatch):
    """If the server sends Retry-After=600, the honored wait must be capped
    at _429_RETRY_AFTER_CAP_S to avoid multi-minute stalls."""
    session = _fake_session([
        _FakeResponse(429, {"Retry-After": "600"}),
        _FakeResponse(200),
    ])
    slept: list[float] = []
    monkeypatch.setattr(dwi.time, "sleep", slept.append)

    dwi.http_get(session, "https://example.invalid/file.png")

    assert len(slept) == 1
    assert slept[0] == dwi._429_RETRY_AFTER_CAP_S
    assert slept[0] < 600


def test_5xx_retries_unchanged(monkeypatch):
    """5xx retry path is unchanged: still retries with exponential backoff
    up to MAX_RETRIES and eventually raises if it never recovers."""
    monkeypatch.setattr(dwi, "MAX_RETRIES", 3)
    session = _fake_session([
        _FakeResponse(503),
        _FakeResponse(503),
        _FakeResponse(200),
    ])
    slept: list[float] = []
    monkeypatch.setattr(dwi.time, "sleep", slept.append)

    resp = dwi.http_get(session, "https://example.invalid/file.png")
    assert resp.status_code == 200
    assert len(slept) == 2, "expected two 5xx retry waits"
