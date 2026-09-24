import unittest

from agent_session_viewer.providers.codex import _parse_codex_response_item


class CodexReasoningTests(unittest.TestCase):
    def test_reasoning_summary_string_is_renderable(self):
        message = _parse_codex_response_item(
            {
                "type": "reasoning",
                "summary": "A readable reasoning summary.",
                "encrypted_content": "opaque payload",
            },
            {},
        )

        self.assertIsNotNone(message)
        self.assertEqual(
            message.content,
            "[thinking] A readable reasoning summary.",
        )

    def test_reasoning_summary_text_items_are_joined(self):
        message = _parse_codex_response_item(
            {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "First summary."},
                    {"type": "summary_text", "text": "Second summary."},
                    {"type": "opaque", "text": "not displayable"},
                ],
                "encrypted_content": "opaque payload",
            },
            {},
        )

        self.assertIsNotNone(message)
        self.assertEqual(
            message.content,
            "[thinking] First summary.\nSecond summary.",
        )

    def test_encrypted_reasoning_without_summary_is_not_rendered(self):
        message = _parse_codex_response_item(
            {
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "opaque payload",
            },
            {},
        )

        self.assertIsNone(message)


if __name__ == "__main__":
    unittest.main()
