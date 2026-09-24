import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.parser import Message, Session, Turn
from agent_session_viewer.pages.session_detail import _apply_provider_cost
from agent_session_viewer.pricing import (
    cost_by_type,
    estimate_usage_cost,
    get_pricing,
)
from agent_session_viewer.providers.codex import CodexProvider, get_codex_pricing
from agent_session_viewer.providers.opencode import OpencodeProvider, _usage_from


class PricingTests(unittest.TestCase):
    def test_claude_model_prefixes_use_current_rates(self):
        opus_55 = get_pricing("claude-opus-5-5-20260901")
        self.assertIsNotNone(opus_55)
        self.assertEqual((opus_55.input, opus_55.output), (4.0, 20.0))
        self.assertEqual(opus_55.cache_write_1h, 8.0)

        opus_41 = get_pricing("claude-opus-4-1-20240229")
        self.assertIsNotNone(opus_41)
        self.assertEqual((opus_41.input, opus_41.output), (15.0, 75.0))

    def test_claude_cache_creation_uses_ttl_breakdown(self):
        costs = estimate_usage_cost(
            "claude-opus-5-5",
            {
                "cache_creation_input_tokens": 200_000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100_000,
                    "ephemeral_1h_input_tokens": 100_000,
                },
            },
        )
        self.assertEqual(costs["cache_create"], 1.3)

    def test_openai_long_context_rates_apply_past_272k(self):
        pricing = get_codex_pricing("gpt-6-sol")
        self.assertIsNotNone(pricing)
        self.assertEqual(pricing.rates_for(272_000).input, 2.0)
        self.assertEqual(pricing.rates_for(272_001).input, 4.0)

        costs = cost_by_type(pricing, {
            "input_tokens": 272_001,
            "output_tokens": 1_000_000,
        })
        self.assertEqual(costs["input"], 1.088004)
        self.assertEqual(costs["output"], 15.0)

    def test_opencode_openai_provider_reprices_long_context_and_cache_tokens(self):
        session = Session(
            session_id="pricing-check",
            turns=[Turn(number=1, messages=[Message(
                role="assistant",
                model="openai/gpt-6-sol",
                usage={
                    "input_tokens": 1_000_000,
                    "output_tokens": 100_000,
                    "cache_read_input_tokens": 100_000,
                    "cache_creation_input_tokens": 200_000,
                },
            )])],
        )

        repriced = _apply_provider_cost(session, OpencodeProvider())
        self.assertAlmostEqual(repriced.estimated_cost, 6.54)

    def test_opencode_reasoning_tokens_are_billed_as_output(self):
        usage = _usage_from({
            "tokens": {
                "input": 100,
                "output": 50,
                "reasoning": 25,
                "cache": {"read": 10, "write": 5},
            },
        })
        self.assertEqual(usage["output_tokens"], 50)
        self.assertEqual(usage["reasoning_tokens"], 25)

        session = Session(
            session_id="reasoning-check",
            turns=[Turn(number=1, messages=[Message(
                role="assistant",
                model="openai/gpt-6-luna",
                usage=usage,
            )])],
        )
        self.assertEqual(session.turns[0].total_tokens, 175)
        costs = _apply_provider_cost(session, OpencodeProvider()).cost_by_type
        self.assertEqual(costs["output"], 0.000025)
        self.assertEqual(costs["reasoning"], 0.0000125)

    def test_codex_token_count_flows_into_openai_cost_evaluation(self):
        entries = [
            {"type": "session_meta", "payload": {"session_id": "codex-check"}},
            {"type": "turn_context", "payload": {"model": "gpt-6-luna"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done"}],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 1_000,
                            "cached_input_tokens": 200,
                            "output_tokens": 100,
                            "reasoning_output_tokens": 20,
                        },
                    },
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "rollout-check.jsonl"
            session_path.write_text(
                "\n".join(json.dumps(entry) for entry in entries),
                encoding="utf-8",
            )
            session = CodexProvider(
                include_default_memory=False,
            ).parse_session(session_path)

        assistant = next(
            message
            for turn in session.turns
            for message in turn.messages
            if message.role == "assistant"
        )
        self.assertEqual(assistant.model, "gpt-6-luna")
        self.assertEqual(assistant.usage["input_tokens"], 800)
        self.assertEqual(assistant.usage["cache_read_input_tokens"], 200)
        self.assertEqual(assistant.usage["output_tokens"], 80)
        self.assertEqual(assistant.usage["reasoning_tokens"], 20)
        self.assertAlmostEqual(
            _apply_provider_cost(
                session, CodexProvider(include_default_memory=False),
            ).estimated_cost,
            0.000132,
        )

    def test_unknown_qwen_model_remains_zero_cost(self):
        self.assertIsNone(OpencodeProvider().get_pricing("qwen/qwen3-coder"))
        costs = estimate_usage_cost(
            "qwen/qwen3-coder",
            {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        )
        self.assertEqual(sum(costs.values()), 0.0)

        session = Session(
            session_id="qwen-check",
            turns=[Turn(number=1, messages=[Message(
                role="assistant",
                model="qwen/qwen3-coder",
                usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
            )])],
        )
        self.assertEqual(
            _apply_provider_cost(session, OpencodeProvider()).estimated_cost,
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
