"""Provider-free checks run inside the built gateway image with network disabled."""
import unittest

import httpx

from litellm.llms.custom_httpx.http_handler import (
    MaskedHTTPStatusError,
    _raise_masked_async_error,
)


class MultipartErrors(unittest.IsolatedAsyncioTestCase):
    async def test_provider_rejection_survives_unread_multipart_upload(self):
        request = httpx.Request(
            "POST", "https://api.openai.com/v1/images/edits",
            data={"model": "gpt-image-2.5-sunburst"},
            files=[("image[]", ("reference.png", b"reference-bytes", "image/png"))],
        )
        with self.assertRaises(httpx.RequestNotRead):
            _ = request.content
        body = {"error": {"message": "Invalid image parameter", "type": "invalid_request_error"}}
        response = httpx.Response(400, json=body, request=request, headers={"x-request-id": "test"})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as original:
            with self.assertRaises(MaskedHTTPStatusError) as caught:
                await _raise_masked_async_error(original, False)
        self.assertEqual(caught.exception.response.status_code, 400)
        self.assertEqual(caught.exception.response.json(), body)
        self.assertIn("Invalid image parameter", caught.exception.text)
        self.assertEqual(caught.exception.response.headers["x-request-id"], "test")
        self.assertEqual(caught.exception.request.content, b"")
        with self.assertRaises(httpx.RequestNotRead):
            _ = request.content

    async def test_server_errors_keep_their_ambiguous_status(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/images/edits", content=b"upload")
        response = httpx.Response(500, text="Internal error", request=request)
        original = httpx.HTTPStatusError("Internal error", request=request, response=response)
        with self.assertRaises(MaskedHTTPStatusError) as caught:
            await _raise_masked_async_error(original, False)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.response.text, "Internal error")


if __name__ == "__main__":
    unittest.main()
