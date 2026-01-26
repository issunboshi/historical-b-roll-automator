"""
Tests for context extraction functions in enrich_entities.py

These tests validate:
- Single mention context extraction (~100-150 words from surrounding cues)
- Multiple mentions context merging with " [...] " separator
- Overlapping window deduplication
- Edge cases: first cue, last cue, invalid cue_idx
"""
import pytest
from dataclasses import dataclass


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
