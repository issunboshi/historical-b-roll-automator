"""Tests for resilient Wikipedia validation in generate_search_strategies.py.

Focus: validate_strategies() must not abort the whole pass when a single
title's API call fails. Policy A (optimistic) — synthesize a "valid" result
for the failing title and continue, keeping the query in the validated set.
The downstream download step does its own MediaWiki lookup with retries.

Background: wikipediaapi calls r.json() unguarded; an empty/HTML response
from Wikipedia's edge raises json.JSONDecodeError which used to bubble up
through validate_strategies() and exit the script with code 1, forfeiting
the upstream LLM spend.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tools.generate_search_strategies import validate_strategies


def _strategies_map(entity_name: str = "Bob Smith") -> dict:
    """Minimal enriched_map with one entity carrying search_strategies."""
    return {
        "entities": {
            entity_name: {
                "entity_type": "people",
                "context": "test",
                "search_strategies": {
                    "best_title": entity_name,
                    "queries": [entity_name, "Bob Smith author", "Robert Smith"],
                    "confidence": 8,
                },
            }
        }
    }


def _fake_validator(side_effects: dict[str, object]) -> MagicMock:
    """Build a validator double whose .validate(title) consults side_effects.

    Values that are exceptions are raised; dicts are returned as-is.
    The .cache.get(...) call is stubbed to None (no cache hit) so the
    cache-hit counter stays out of the way.
    """
    validator = MagicMock()
    validator.cache.get.return_value = None

    def _validate(title: str):
        outcome = side_effects[title]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    validator.validate.side_effect = _validate
    return validator


def test_validate_strategies_swallows_per_title_errors():
    """A JSONDecodeError on one query must not abort the whole pass.

    Policy A: the failing query is treated as exists=True, canonical=None,
    and stays in the validated query list.
    """
    enriched = _strategies_map()

    validator = _fake_validator({
        # best_title validates fine
        "Bob Smith": {
            "exists": True,
            "canonical_title": "Bob Smith",
            "canonical_url": "https://en.wikipedia.org/wiki/Bob_Smith",
        },
        # second query raises the exact error we saw in production
        "Bob Smith author": json.JSONDecodeError("Expecting value", "", 0),
        # third query genuinely doesn't exist
        "Robert Smith": {
            "exists": False,
            "canonical_title": None,
            "canonical_url": None,
        },
    })

    result = validate_strategies(enriched, validator)

    strategies = result["entities"]["Bob Smith"]["search_strategies"]

    # The failing query is kept (Policy A optimistic):
    assert "Bob Smith author" in strategies["queries"]
    # The genuinely-invalid one is dropped:
    assert "Robert Smith" not in strategies["queries"]
    # The valid one is kept:
    assert "Bob Smith" in strategies["queries"]

    # validated_queries records all three, with the error treated as valid
    # but with canonical=None (the signal it wasn't actually checked).
    by_query = {v["query"]: v for v in strategies["validated_queries"]}
    assert by_query["Bob Smith author"]["valid"] is True
    assert by_query["Bob Smith author"]["canonical"] is None
    assert by_query["Robert Smith"]["valid"] is False


def test_validate_strategies_logs_error_count(capsys):
    """The end-of-function summary must mention the API error count."""
    enriched = _strategies_map()

    validator = _fake_validator({
        "Bob Smith": {"exists": True, "canonical_title": "Bob Smith", "canonical_url": "x"},
        "Bob Smith author": ValueError("boom"),
        "Robert Smith": {"exists": True, "canonical_title": "Robert Smith", "canonical_url": "y"},
    })

    validate_strategies(enriched, validator)

    err = capsys.readouterr().err
    assert "1 API errors" in err
    # And the per-error warning that points the user at the offending title:
    assert "Bob Smith author" in err


def test_validate_strategies_no_errors_no_count_in_summary(capsys):
    """When validation has zero errors, the summary line stays clean."""
    enriched = _strategies_map()

    validator = _fake_validator({
        "Bob Smith": {"exists": True, "canonical_title": "Bob Smith", "canonical_url": "x"},
        "Bob Smith author": {"exists": True, "canonical_title": "Bob Smith", "canonical_url": "x"},
        "Robert Smith": {"exists": True, "canonical_title": "Robert Smith", "canonical_url": "y"},
    })

    validate_strategies(enriched, validator)

    err = capsys.readouterr().err
    assert "API errors" not in err
    assert "Validation complete" in err
