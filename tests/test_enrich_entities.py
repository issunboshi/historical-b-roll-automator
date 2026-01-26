"""
Tests for enrich_entities.py

This file includes tests for:
1. Priority Scoring (Plan 01-01):
   - TYPE_WEIGHTS constant with 5 entity types
   - srt_time_to_seconds timecode parsing
   - mention_multiplier with diminishing returns
   - position_multiplier with early mention boost
   - calculate_priority combining all factors

2. Context Extraction (Plan 01-02):
   - Single mention context extraction (~100-150 words from surrounding cues)
   - Multiple mentions context merging with " [...] " separator
   - Overlapping window deduplication
   - Edge cases: first cue, last cue, invalid cue_idx
"""
import pytest
from dataclasses import dataclass

from tools.enrich_entities import (
    TYPE_WEIGHTS,
    calculate_priority,
    mention_multiplier,
    position_multiplier,
    srt_time_to_seconds,
)


# =============================================================================
# Priority Scoring Tests (Plan 01-01)
# =============================================================================

class TestTypeWeights:
    """Tests for TYPE_WEIGHTS constant."""

    def test_people_weight_is_highest(self):
        """People type should have highest weight (1.0)."""
        assert TYPE_WEIGHTS["people"] == 1.0

    def test_events_weight(self):
        """Events type should have weight 0.9."""
        assert TYPE_WEIGHTS["events"] == 0.9

    def test_organizations_weight(self):
        """Organizations type should have weight 0.7."""
        assert TYPE_WEIGHTS["organizations"] == 0.7

    def test_concepts_weight(self):
        """Concepts type should have weight 0.6."""
        assert TYPE_WEIGHTS["concepts"] == 0.6

    def test_places_weight_is_lowest(self):
        """Places type should have lowest weight (0.3)."""
        assert TYPE_WEIGHTS["places"] == 0.3

    def test_contains_all_five_types(self):
        """TYPE_WEIGHTS should contain exactly 5 entity types."""
        expected_types = {"people", "events", "organizations", "concepts", "places"}
        assert set(TYPE_WEIGHTS.keys()) == expected_types


class TestSrtTimeToSeconds:
    """Tests for srt_time_to_seconds helper function."""

    def test_zero_time(self):
        """00:00:00,000 should return 0.0."""
        assert srt_time_to_seconds("00:00:00,000") == 0.0

    def test_one_minute(self):
        """00:01:00,000 should return 60.0."""
        assert srt_time_to_seconds("00:01:00,000") == 60.0

    def test_one_hour(self):
        """01:00:00,000 should return 3600.0."""
        assert srt_time_to_seconds("01:00:00,000") == 3600.0

    def test_milliseconds(self):
        """00:00:01,500 should return 1.5."""
        assert srt_time_to_seconds("00:00:01,500") == 1.5

    def test_complex_time(self):
        """01:23:45,678 should return correct seconds."""
        expected = 1 * 3600 + 23 * 60 + 45 + 0.678
        assert abs(srt_time_to_seconds("01:23:45,678") - expected) < 0.001

    def test_invalid_format_returns_zero(self):
        """Invalid format should return 0.0."""
        assert srt_time_to_seconds("invalid") == 0.0
        assert srt_time_to_seconds("") == 0.0


class TestMentionMultiplier:
    """Tests for mention_multiplier function."""

    def test_one_mention(self):
        """1 mention should return 1.0x multiplier."""
        assert mention_multiplier(1) == 1.0

    def test_two_mentions(self):
        """2 mentions should return 1.3x multiplier."""
        assert mention_multiplier(2) == 1.3

    def test_three_mentions(self):
        """3 mentions should return 1.5x multiplier."""
        assert mention_multiplier(3) == 1.5

    def test_four_mentions(self):
        """4 mentions should return 1.6x multiplier."""
        assert mention_multiplier(4) == 1.6

    def test_five_plus_mentions(self):
        """5+ mentions should still return 1.6x (max)."""
        assert mention_multiplier(5) == 1.6
        assert mention_multiplier(10) == 1.6
        assert mention_multiplier(100) == 1.6

    def test_zero_mentions(self):
        """0 mentions edge case should return 1.0x."""
        assert mention_multiplier(0) == 1.0


class TestPositionMultiplier:
    """Tests for position_multiplier function."""

    def test_early_position_gets_boost(self):
        """Position in first 20% should get 1.1x boost."""
        assert position_multiplier(0.0) == 1.1   # Start of transcript
        assert position_multiplier(0.1) == 1.1   # 10% in
        assert position_multiplier(0.19) == 1.1  # Just under 20%

    def test_boundary_at_20_percent(self):
        """Position at exactly 20% should get boost (<=20%)."""
        assert position_multiplier(0.2) == 1.1

    def test_after_20_percent_no_boost(self):
        """Position after 20% should return 1.0x (no boost)."""
        assert position_multiplier(0.21) == 1.0
        assert position_multiplier(0.5) == 1.0
        assert position_multiplier(1.0) == 1.0

    def test_negative_position_treated_as_early(self):
        """Negative position (edge case) treated as early."""
        assert position_multiplier(-0.1) == 1.1


class TestCalculatePriority:
    """Tests for calculate_priority function with full entity dicts."""

    def test_person_one_mention_early(self):
        """Person, 1 mention, early (20%): 1.0 * 1.0 * 1.1 = 1.1"""
        entity = {
            "entity_type": "people",
            "occurrences": [{"timecode": "00:01:00,000"}]  # 60s into 600s = 10%
        }
        transcript_duration = 600.0  # 10 minutes
        result = calculate_priority(entity, transcript_duration)
        assert abs(result - 1.1) < 0.01

    def test_person_four_mentions_early_capped(self):
        """Person, 4 mentions, early: 1.0 * 1.6 * 1.1 = 1.76 -> capped to 1.2"""
        entity = {
            "entity_type": "people",
            "occurrences": [
                {"timecode": "00:00:30,000"},  # 30s into 600s = 5% (early)
                {"timecode": "00:02:00,000"},
                {"timecode": "00:03:00,000"},
                {"timecode": "00:04:00,000"},
            ]
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        assert result == 1.2  # Capped

    def test_place_one_mention_late(self):
        """Place, 1 mention, late: 0.3 * 1.0 * 1.0 = 0.3"""
        entity = {
            "entity_type": "places",
            "occurrences": [{"timecode": "00:05:00,000"}]  # 300s into 600s = 50%
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        assert abs(result - 0.3) < 0.01

    def test_event_two_mentions_early_capped(self):
        """Event, 2 mentions, early: 0.9 * 1.3 * 1.1 = 1.287 -> capped to 1.2"""
        entity = {
            "entity_type": "events",
            "occurrences": [
                {"timecode": "00:00:30,000"},  # 30s = 5% (early)
                {"timecode": "00:02:00,000"},
            ]
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        assert result == 1.2  # Capped

    def test_concept_three_mentions_late(self):
        """Concept, 3 mentions, late: 0.6 * 1.5 * 1.0 = 0.9"""
        entity = {
            "entity_type": "concepts",
            "occurrences": [
                {"timecode": "00:03:00,000"},  # 180s = 30% (late)
                {"timecode": "00:04:00,000"},
                {"timecode": "00:05:00,000"},
            ]
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        assert abs(result - 0.9) < 0.01

    def test_unknown_type_defaults_to_half(self):
        """Unknown type should default to 0.5 base weight."""
        entity = {
            "entity_type": "unknown_type",
            "occurrences": [{"timecode": "00:03:00,000"}]  # Late
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        # 0.5 * 1.0 * 1.0 = 0.5
        assert abs(result - 0.5) < 0.01

    def test_organization_type(self):
        """Organization, 2 mentions, early: 0.7 * 1.3 * 1.1 = 1.001"""
        entity = {
            "entity_type": "organizations",
            "occurrences": [
                {"timecode": "00:00:30,000"},  # 5% (early)
                {"timecode": "00:02:00,000"},
            ]
        }
        transcript_duration = 600.0
        result = calculate_priority(entity, transcript_duration)
        expected = 0.7 * 1.3 * 1.1  # = 1.001
        assert abs(result - expected) < 0.01


class TestPriorityEdgeCases:
    """Tests for edge cases in priority calculation."""

    def test_empty_occurrences_returns_zero(self):
        """Entity with no occurrences should return 0.0."""
        entity = {
            "entity_type": "people",
            "occurrences": []
        }
        result = calculate_priority(entity, 600.0)
        assert result == 0.0

    def test_zero_duration_handles_gracefully(self):
        """Zero transcript duration should not cause division by zero."""
        entity = {
            "entity_type": "people",
            "occurrences": [{"timecode": "00:00:30,000"}]
        }
        # Should not raise, should return sensible value
        result = calculate_priority(entity, 0.0)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.2

    def test_missing_entity_type_key(self):
        """Entity without entity_type key should use default weight."""
        entity = {
            "occurrences": [{"timecode": "00:03:00,000"}]
        }
        result = calculate_priority(entity, 600.0)
        # Should default to 0.5 * 1.0 * 1.0 = 0.5
        assert abs(result - 0.5) < 0.01

    def test_score_never_exceeds_cap(self):
        """Score should never exceed 1.2 regardless of inputs."""
        entity = {
            "entity_type": "people",  # 1.0
            "occurrences": [
                {"timecode": "00:00:01,000"},  # Very early
                {"timecode": "00:00:02,000"},
                {"timecode": "00:00:03,000"},
                {"timecode": "00:00:04,000"},
                {"timecode": "00:00:05,000"},
                {"timecode": "00:00:06,000"},
                {"timecode": "00:00:07,000"},
                {"timecode": "00:00:08,000"},
                {"timecode": "00:00:09,000"},
                {"timecode": "00:00:10,000"},  # 10 mentions
            ]
        }
        result = calculate_priority(entity, 600.0)
        assert result == 1.2

    def test_score_minimum_is_zero(self):
        """Score should be at least 0.0."""
        entity = {
            "entity_type": "places",  # Lowest weight
            "occurrences": [{"timecode": "00:05:00,000"}]  # Late
        }
        result = calculate_priority(entity, 600.0)
        assert result >= 0.0

    def test_malformed_timecode_treated_as_zero_position(self):
        """Malformed timecode should be treated as position 0 (early)."""
        entity = {
            "entity_type": "people",
            "occurrences": [{"timecode": "invalid"}]
        }
        # Position 0 is early, so 1.0 * 1.0 * 1.1 = 1.1
        result = calculate_priority(entity, 600.0)
        assert abs(result - 1.1) < 0.01


# =============================================================================
# Context Extraction Tests (Plan 01-02)
# =============================================================================


# Mock SrtCue to match the structure from srt_entities.py
@dataclass
class MockSrtCue:
    """Mock cue for testing, matching SrtCue interface."""
    index: int
    start: str = "00:00:00,000"
    end: str = "00:00:05,000"
    text: str = ""


def make_cues(count: int, words_per_cue: int = 20) -> list:
    """Create a list of mock cues with predictable text content.

    Each cue text is: "Cue{index} word1 word2 word3..." (words_per_cue words total)
    """
    cues = []
    for i in range(1, count + 1):
        words = [f"Cue{i}"] + [f"word{j}" for j in range(1, words_per_cue)]
        text = " ".join(words)
        cues.append(MockSrtCue(index=i, text=text))
    return cues


class TestExtractSingleContext:
    """Tests for extract_single_context helper function."""

    def test_returns_tuple_with_indices_and_text(self):
        """extract_single_context returns (start_idx, end_idx, context_text)."""
        from tools.enrich_entities import extract_single_context

        cues = make_cues(10)
        start_idx, end_idx, text = extract_single_context(cues, cue_idx=5, window_cues=3)

        # Should return tuple with 3 elements
        assert isinstance(start_idx, int)
        assert isinstance(end_idx, int)
        assert isinstance(text, str)

    def test_extracts_window_before_and_after(self):
        """With cue_idx=5 and window=3, should extract cues 2-8 (indices 1-7 in 0-based)."""
        from tools.enrich_entities import extract_single_context

        cues = make_cues(10)
        start_idx, end_idx, text = extract_single_context(cues, cue_idx=5, window_cues=3)

        # 5 - 3 = 2 (min cue index), 5 + 3 = 8 (max cue index)
        assert start_idx == 2
        assert end_idx == 8
        # Text should contain content from cues 2-8
        assert "Cue2" in text
        assert "Cue5" in text
        assert "Cue8" in text
        assert "Cue1" not in text  # Before window
        assert "Cue9" not in text  # After window

    def test_first_cue_edge_case(self):
        """When cue_idx=1 (first), should not go negative - start at cue 1."""
        from tools.enrich_entities import extract_single_context

        cues = make_cues(10)
        start_idx, end_idx, text = extract_single_context(cues, cue_idx=1, window_cues=3)

        # Can't go before cue 1, so start at 1
        assert start_idx == 1
        assert end_idx == 4  # 1 + 3
        assert "Cue1" in text
        assert "Cue4" in text

    def test_last_cue_edge_case(self):
        """When cue_idx is last cue, should not exceed cue count."""
        from tools.enrich_entities import extract_single_context

        cues = make_cues(10)
        start_idx, end_idx, text = extract_single_context(cues, cue_idx=10, window_cues=3)

        # Can't go past cue 10
        assert start_idx == 7  # 10 - 3
        assert end_idx == 10
        assert "Cue7" in text
        assert "Cue10" in text

    def test_invalid_cue_idx_returns_empty(self):
        """When cue_idx not found, returns empty context."""
        from tools.enrich_entities import extract_single_context

        cues = make_cues(10)
        start_idx, end_idx, text = extract_single_context(cues, cue_idx=99, window_cues=3)

        # No cue with index 99
        assert start_idx == -1
        assert end_idx == -1
        assert text == ""


class TestMergeContextWindows:
    """Tests for merge_context_windows function."""

    def test_single_window_returns_text_as_is(self):
        """A single context window should return just its text."""
        from tools.enrich_entities import merge_context_windows

        windows = [(1, 5, "This is the context text.")]
        result = merge_context_windows(windows)

        assert result == "This is the context text."

    def test_non_overlapping_windows_joined_with_separator(self):
        """Non-overlapping windows should be joined with ' [...] '."""
        from tools.enrich_entities import merge_context_windows

        # Windows (1-5) and (10-15) don't overlap
        windows = [
            (1, 5, "First context."),
            (10, 15, "Second context."),
        ]
        result = merge_context_windows(windows)

        assert result == "First context. [...] Second context."

    def test_overlapping_windows_merged(self):
        """Overlapping windows should be merged into single context."""
        from tools.enrich_entities import merge_context_windows

        # Windows (1-7) and (5-12) overlap at indices 5-7
        windows = [
            (1, 7, "Cue1 Cue2 Cue3 Cue4 Cue5 Cue6 Cue7"),
            (5, 12, "Cue5 Cue6 Cue7 Cue8 Cue9 Cue10 Cue11 Cue12"),
        ]
        result = merge_context_windows(windows)

        # Should merge without duplicating the overlapping portion
        # Result should cover indices 1-12 without repeating 5-7
        assert "Cue1" in result
        assert "Cue12" in result
        # Should not have " [...] " since they overlap
        assert " [...] " not in result

    def test_empty_windows_returns_empty_string(self):
        """Empty window list returns empty string."""
        from tools.enrich_entities import merge_context_windows

        result = merge_context_windows([])
        assert result == ""

    def test_adjacent_windows_treated_as_overlapping(self):
        """Windows that are adjacent (end == start - 1) should merge."""
        from tools.enrich_entities import merge_context_windows

        # Windows (1-5) and (6-10) are adjacent
        windows = [
            (1, 5, "Part one text."),
            (6, 10, "Part two text."),
        ]
        result = merge_context_windows(windows)

        # Adjacent windows merge without separator
        assert " [...] " not in result


class TestExtractEntityContext:
    """Tests for the main extract_entity_context function."""

    def test_single_mention_returns_surrounding_context(self):
        """Single occurrence returns context from surrounding cues."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10)
        occurrences = [{"cue_idx": 5}]

        result = extract_entity_context(cues, occurrences, window_cues=3)

        # Should have content from cues 2-8
        assert "Cue2" in result
        assert "Cue5" in result
        assert "Cue8" in result
        assert len(result) > 0

    def test_two_mentions_far_apart_joined_with_separator(self):
        """Two mentions far apart get joined with ' [...] '."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(20)
        # Occurrences at cue 3 and cue 17 - windows won't overlap
        occurrences = [
            {"cue_idx": 3},
            {"cue_idx": 17},
        ]

        result = extract_entity_context(cues, occurrences, window_cues=2)

        # Should have separator between the two contexts
        assert " [...] " in result
        # Should have content from both windows
        assert "Cue3" in result
        assert "Cue17" in result

    def test_two_mentions_close_together_merged(self):
        """Two mentions close together (overlapping windows) merge into one context."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10)
        # Occurrences at cue 4 and cue 6 - with window=3, these overlap
        # Cue 4 window: 1-7
        # Cue 6 window: 3-9
        occurrences = [
            {"cue_idx": 4},
            {"cue_idx": 6},
        ]

        result = extract_entity_context(cues, occurrences, window_cues=3)

        # Should NOT have separator - windows overlap
        assert " [...] " not in result
        # Should have content spanning both windows (1-9)
        assert "Cue1" in result
        assert "Cue9" in result

    def test_empty_occurrences_returns_empty(self):
        """Empty occurrences list returns empty string."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10)
        result = extract_entity_context(cues, [], window_cues=3)

        assert result == ""

    def test_invalid_cue_idx_skipped(self):
        """Occurrences with invalid cue_idx are skipped."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10)
        occurrences = [
            {"cue_idx": 99},  # Invalid
            {"cue_idx": 5},   # Valid
        ]

        result = extract_entity_context(cues, occurrences, window_cues=3)

        # Should have content from cue 5 only
        assert "Cue5" in result
        assert len(result) > 0

    def test_strips_speaker_labels(self):
        """Speaker labels like 'Speaker 2' are stripped from context."""
        from tools.enrich_entities import extract_entity_context

        # Create cues with speaker labels in text
        cues = [
            MockSrtCue(index=1, text="Speaker 1\nFirst cue content."),
            MockSrtCue(index=2, text="Speaker 2\nSecond cue content."),
            MockSrtCue(index=3, text="Third cue content."),
        ]
        occurrences = [{"cue_idx": 2}]

        result = extract_entity_context(cues, occurrences, window_cues=1)

        # Speaker labels should be stripped
        assert "Speaker 1" not in result
        assert "Speaker 2" not in result
        # Content should remain
        assert "cue content" in result

    def test_collapses_whitespace(self):
        """Multiple whitespace characters are collapsed to single space."""
        from tools.enrich_entities import extract_entity_context

        cues = [
            MockSrtCue(index=1, text="Word1   word2\n\nword3"),
            MockSrtCue(index=2, text="Word4  word5"),
        ]
        occurrences = [{"cue_idx": 1}]

        result = extract_entity_context(cues, occurrences, window_cues=1)

        # Should not have multiple consecutive spaces
        assert "  " not in result
        assert "\n" not in result

    def test_default_window_is_three(self):
        """Default window_cues should be 3."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10)
        occurrences = [{"cue_idx": 5}]

        # Call without specifying window_cues
        result = extract_entity_context(cues, occurrences)

        # Should use default window of 3, getting cues 2-8
        assert "Cue2" in result
        assert "Cue8" in result

    def test_word_count_approximately_100_150(self):
        """With 7 cues of 20 words each, should get ~100-150 words."""
        from tools.enrich_entities import extract_entity_context

        cues = make_cues(10, words_per_cue=20)
        occurrences = [{"cue_idx": 5}]

        result = extract_entity_context(cues, occurrences, window_cues=3)

        word_count = len(result.split())
        # 7 cues * ~20 words = ~140 words, allow some variance
        assert 80 <= word_count <= 180, f"Got {word_count} words, expected 80-180"
