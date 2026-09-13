"""Provider-free checks run inside the patched gateway image with network disabled."""
import unittest

from patch_anthropic_refusals import patch_source
from litellm.llms.anthropic.chat.handler import ModelResponseIterator
from litellm.llms.anthropic.chat.transformation import AnthropicConfig


class AnthropicRefusalDetails(unittest.TestCase):
    details = {"type": "refusal", "category": "general_harms", "explanation": "Test refusal"}

    def test_stream_preserves_details_and_refusal_finish_reason(self):
        iterator = ModelResponseIterator(iter(()), sync_stream=True)
        chunk = iterator.chunk_parser({
            "type": "message_delta",
            "delta": {"stop_reason": "refusal", "stop_details": self.details},
            "usage": {"output_tokens": 0},
        }).model_dump()
        choice = chunk["choices"][0]
        self.assertEqual(choice["finish_reason"], "content_filter")
        self.assertEqual(choice["delta"]["provider_specific_fields"]["stop_details"], self.details)

    def test_buffered_response_preserves_details(self):
        fields = AnthropicConfig()._build_provider_specific_fields(
            {"stop_details": self.details}, None, None, None, None, None, []
        )
        self.assertEqual(fields["stop_details"], self.details)

    def test_success_does_not_invent_refusal_details(self):
        fields = AnthropicConfig()._build_provider_specific_fields(
            {}, None, None, None, None, None, []
        )
        self.assertNotIn("stop_details", fields)

    def test_patch_is_idempotent_and_rejects_changed_upstream(self):
        for kind, source in (
            ("transformation", '        context_management = completion_response.get("context_management")'),
            ("handler", '                finish_reason, usage, container = self._handle_message_delta(chunk)'),
        ):
            patched = patch_source(source, kind)
            self.assertEqual(patch_source(patched, kind), patched)
            with self.assertRaises(RuntimeError):
                patch_source("unrecognized upstream source", kind)


if __name__ == "__main__":
    unittest.main()
