"""Tests for text utilities (text_utils.py)."""


from novel_to_comic.text_utils import clean, shorten, clean_exception_message


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


class TestCleanExceptionMessage:
    def test_generic_exception(self):
        exc = ValueError("Some standard error message")
        assert clean_exception_message(exc) == "Some standard error message"

    def test_strip_mozilla_url(self):
        exc = Exception(
            "Server error '500 Internal Server Error' for url 'http://localhost:4000/v1/images/generations'\n"
            "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
        )
        expected = "Server error '500 Internal Server Error' for url 'http://localhost:4000/v1/images/generations'"
        assert clean_exception_message(exc) == expected

    def test_httpx_status_error_json_error(self):
        import httpx
        request = httpx.Request("POST", "http://localhost:4000/v1/images/generations")
        response = httpx.Response(
            status_code=500,
            request=request,
            json={"error": {"message": "REVE_API_KEY is not set"}}
        )
        exc = httpx.HTTPStatusError("500 Internal Server Error", request=request, response=response)
        assert clean_exception_message(exc) == "HTTPStatusError: 500 Internal Server Error - REVE_API_KEY is not set"

    def test_httpx_status_error_json_detail(self):
        import httpx
        request = httpx.Request("POST", "http://localhost:4000/v1/images/generations")
        response = httpx.Response(
            status_code=400,
            request=request,
            json={"detail": "Invalid model parameter"}
        )
        exc = httpx.HTTPStatusError("400 Bad Request", request=request, response=response)
        assert clean_exception_message(exc) == "HTTPStatusError: 400 Bad Request - Invalid model parameter"

    def test_httpx_read_timeout_is_not_an_empty_error(self):
        import httpx

        request = httpx.Request("POST", "http://localhost:4000/v1/chat/completions")
        exc = httpx.ReadTimeout("", request=request)

        assert clean_exception_message(exc) == (
            "ReadTimeout: The AI provider did not respond before the request timeout."
        )
