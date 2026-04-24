"""Tests for text utilities (text_utils.py)."""

import pytest

from novel_to_comic.text_utils import clean, shorten


class TestClean:
    def test_strips_leading_trailing_whitespace(self):
        assert clean("  hello world  ") == "hello world"

    def test_collapse_newlines_to_spaces(self):
        assert clean("hello\nworld\n") == "hello world"

    def test_collapse_multiple_spaces_to_one(self):
        assert clean("hello    world") == "hello world"

    def test_handles_none(self):
        assert clean(None) == ""

    def test_handles_empty_string(self):
        assert clean("") == ""

    def test_combined(self):
        assert clean("  hello \n\n world   ") == "hello world"


class TestShorten:
    def test_unchanged_if_under_limit(self):
        assert shorten("hello world", 50) == "hello world"

    def test_truncates_on_word_boundary(self):
        result = shorten("The quick brown fox jumped over the lazy dog", 20)
        assert len(result) <= 20
        assert result.endswith(".")
        assert "jumped" not in result  # broke at a word boundary before "jumped"

    def test_preserves_ending_punctuation(self):
        result = shorten("Hello, world! How are you?", 12)
        # Should end with punctuation
        assert result[-1] in ("!", "?", ".")

    def test_limit_equal_to_length(self):
        text = "hello"
        assert shorten(text, 5) == "hello"

    def test_handles_single_word_over_limit(self):
        result = shorten("supercalifragilisticexpialidocious", 10)
        # Truncates at limit, strips trailing punctuation, adds "."
        assert result.endswith(".")
        # "supercalif." is 11 chars — expected when limit < first word + dot
        assert result == "supercalif."
        assert len(result) <= 11  # limit (10) + 1 for the trailing dot

    def test_under_limit_with_newlines(self):
        result = shorten("hello\n\nworld", 50)
        assert "\n" not in result
        assert "hello world" in result
