"""Tests for priority scoring in enrich_entities module.

Test cases from plan:
- Person, 1 mention, early (20%): 1.0 * 1.0 * 1.1 = 1.1
- Person, 4 mentions, early: 1.0 * 1.6 * 1.1 = 1.76 -> capped to 1.2
- Place, 1 mention, late: 0.3 * 1.0 * 1.0 = 0.3
- Event, 2 mentions, early: 0.9 * 1.3 * 1.1 = 1.287 -> capped to 1.2
- Concept, 3 mentions, late: 0.6 * 1.5 * 1.0 = 0.9
- Unknown type defaults to 0.5 base weight
"""

import pytest

from tools.enrich_entities import (
    TYPE_WEIGHTS,
    calculate_priority,
    mention_multiplier,
    position_multiplier,
    srt_time_to_seconds,
)


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


class TestEdgeCases:
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
