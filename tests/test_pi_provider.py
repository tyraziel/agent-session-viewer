import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import SessionPath
from agent_session_viewer.providers.pi import DEFAULT_SESSIONS_PATH, PiProvider


def _entry(entry_type: str, entry_id: str, parent_id: str | None, **values) -> dict:
    return {
        "type": entry_type,
        "id": entry_id,
        "parentId": parent_id,
        "timestamp": "2026-10-23T10:00:00.000Z",
        **values,
    }


def _write_session(path: Path, entries: list[dict], *, cwd: str = "/workspace/alpha"):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "type": "session",
        "version": 3,
        "id": "session-pi-123",
        "timestamp": "2026-10-23T09:00:00.000Z",
        "cwd": cwd,
    }
    path.write_text(
        "\n".join(json.dumps(entry) for entry in [header, *entries]) + "\n",
        encoding="utf-8",
    )


def _branched_entries() -> list[dict]:
    return [
        _entry(
            "message", "system-1", None,
            message={"role": "system", "content": "System prompt", "timestamp": 1_761_213_600_000},
        ),
        _entry(
            "message", "user-1", "system-1",
            message={"role": "user", "content": "Initial prompt", "timestamp": 1_761_213_601_000},
        ),
        _entry(
            "message", "assistant-old", "user-1",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": "Abandoned branch"}],
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "usage": {"input": 100, "output": 20, "cacheRead": 0, "cacheWrite": 0},
            },
        ),
        _entry(
            "message", "user-branch", "user-1",
            message={"role": "user", "content": "Continue from here", "timestamp": 1_761_213_602_000},
        ),
        _entry(
            "message", "assistant-tool", "user-branch",
            message={
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking now."},
                    {"type": "thinking", "thinking": "Reasoning text"},
                    {
                        "type": "toolCall",
                        "id": "call-1",
                        "name": "read",
                        "arguments": {"path": "README.md"},
                    },
                ],
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input": 10,
                    "output": 5,
                    "reasoning": 2,
                    "cacheRead": 3,
                    "cacheWrite": 1,
                    "totalTokens": 19,
                },
                "timestamp": 1_761_213_603_000,
            },
        ),
        _entry(
            "message", "tool-result-1", "assistant-tool",
            message={
                "role": "toolResult",
                "toolCallId": "call-1",
                "toolName": "read",
                "content": [{"type": "text", "text": "File contents"}],
                "isError": False,
                "timestamp": 1_761_213_604_000,
            },
        ),
        _entry(
            "message", "assistant-final", "tool-result-1",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": "Done."}],
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "usage": {"input": 20, "output": 8, "cacheRead": 0, "cacheWrite": 0},
                "timestamp": 1_761_213_605_000,
            },
        ),
        _entry("session_info", "title-1", "assistant-final", name="Pi test session"),
    ]


class PiProviderTests(unittest.TestCase):
    def test_discover_project_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_path = root / "--workspace-alpha--" / "2026-10-23T10-00-00_session-pi-123.jsonl"
            _write_session(session_path, _branched_entries())

            projects = PiProvider().discover_projects([root])

        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project.name, "workspace-alpha")
        self.assertEqual(project.provider, "pi")
        self.assertEqual(project.path, Path("/workspace/alpha"))
        self.assertEqual(len(project.sessions), 1)
        session_info = project.sessions[0]
        self.assertEqual(session_info.session_id, "session-pi-123")
        self.assertEqual(session_info.path, session_path)
        self.assertEqual(session_info.provider, "pi")
        self.assertEqual(session_info.cwd, "/workspace/alpha")
        self.assertEqual(session_info.title, "Pi test session")
        self.assertEqual(session_info.turn_count, 2)
        self.assertEqual(session_info.api_call_count, 2)
        self.assertEqual(session_info.resume_command, "cd /workspace/alpha && pi --session session-pi-123")

    def test_parses_active_branch_messages_usage_and_tool_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            _write_session(path, _branched_entries())

            session = PiProvider().parse_session(path)

        self.assertEqual(session.session_id, "session-pi-123")
        self.assertEqual(session.model, "anthropic/claude-sonnet-4-5")
        self.assertEqual(session.metadata["title"], "Pi test session")
        self.assertEqual(session.metadata["cwd"], "/workspace/alpha")
        self.assertEqual(session.total_turns, 2)
        self.assertEqual(session.api_call_count, 2)

        second_turn = session.turns[1]
        self.assertEqual(
            [message.role for message in second_turn.messages],
            ["user", "assistant", "assistant", "assistant", "tool_result", "assistant"],
        )
        self.assertEqual(second_turn.messages[0].content, "Continue from here")
        self.assertEqual(second_turn.messages[1].content, "Checking now.")
        self.assertEqual(second_turn.messages[2].content, "[thinking] Reasoning text")
        tool_call = second_turn.messages[3].tool_calls[0]
        self.assertEqual(tool_call.tool_name, "read")
        self.assertEqual(tool_call.tool_input, {"path": "README.md"})
        self.assertEqual(tool_call.tool_id, "call-1")
        tool_result = second_turn.messages[4].tool_results[0]
        self.assertEqual(tool_result.output, "File contents")
        self.assertEqual(tool_result.tool_id, "call-1")
        self.assertEqual(second_turn.messages[5].content, "Done.")

        usage = second_turn.messages[1].usage
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 3)
        self.assertEqual(usage["reasoning_tokens"], 2)
        self.assertEqual(usage["cache_read_input_tokens"], 3)
        self.assertEqual(usage["cache_creation_input_tokens"], 1)
        self.assertEqual(session.total_tokens["input_tokens"], 30)
        self.assertEqual(session.total_tokens["output_tokens"], 11)
        self.assertEqual(session.total_tokens["reasoning_tokens"], 2)

    def test_tail_uses_current_branch_and_omits_reasoning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            _write_session(path, _branched_entries())

            exchanges = PiProvider().extract_tail_exchanges(path)

        self.assertEqual(
            exchanges,
            [
                ("Initial prompt", ""),
                ("Continue from here", "Checking now.\nDone."),
            ],
        )

    def test_v1_linear_entries_are_supported(self):
        entries = [
            {"type": "session", "version": 1, "id": "legacy-id", "cwd": "/workspace/legacy"},
            {"type": "message", "message": {"role": "user", "content": "Hello"}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in entries), encoding="utf-8")

            session = PiProvider().parse_session(path)

        self.assertEqual(session.session_id, "legacy-id")
        self.assertEqual(len(session.turns), 1)
        self.assertEqual(
            [message.content for message in session.turns[0].messages],
            ["Hello", "Hi"],
        )

    def test_recursive_path_and_direct_file_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            root = temp_root / "sessions"
            shallow_file = root / "project" / "session.jsonl"
            _write_session(shallow_file, [], cwd="/workspace/shallow")
            nested_file = root / "project" / "archive" / "session.jsonl"
            _write_session(nested_file, [], cwd="/workspace/nested")
            direct_file = temp_root / "direct.jsonl"
            _write_session(direct_file, [], cwd="/workspace/direct")
            provider = PiProvider()

            default_depth = provider.discover_projects([root])
            shallow = provider.discover_projects([SessionPath(root, recursive=False)])
            recursive = provider.discover_projects([SessionPath(root, recursive=True)])
            direct = provider.discover_projects([direct_file])

        self.assertEqual(len(default_depth), 1)
        self.assertEqual(default_depth[0].path, Path("/workspace/shallow"))
        self.assertEqual(shallow, [])
        self.assertEqual(len(recursive), 2)
        self.assertEqual(len(direct), 1)

    def test_default_path_and_pricing(self):
        provider = PiProvider()
        self.assertEqual(provider.default_paths(), [DEFAULT_SESSIONS_PATH])
        self.assertIsNotNone(provider.get_pricing("anthropic/claude-sonnet-4-5"))
        self.assertIsNotNone(provider.get_pricing("openai/gpt-5.2"))
        self.assertIsNone(provider.get_pricing("google/gemini-custom"))

    def test_standalone_usage_is_counted_without_counting_an_extra_api_call(self):
        entries = [
            _entry(
                "message", "user-1", None,
                message={"role": "user", "content": "Hello"},
            ),
            _entry(
                "usage", "usage-1", "user-1",
                provider="anthropic",
                model="claude-sonnet-4-5",
                kind="cache_warm",
                usage={"input": 4, "output": 0, "cacheRead": 8, "cacheWrite": 0},
            ),
            _entry(
                "message", "assistant-1", "usage-1",
                message={
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hi"}],
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-5",
                    "usage": {"input": 5, "output": 2, "cacheRead": 0, "cacheWrite": 0},
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            _write_session(path, entries)

            session = PiProvider().parse_session(path)

        self.assertEqual(session.api_call_count, 1)
        self.assertEqual(session.total_tokens["input_tokens"], 9)
        self.assertEqual(session.total_tokens["cache_read_input_tokens"], 8)
        self.assertEqual(session.turns[0].messages[1].role, "system")


if __name__ == "__main__":
    unittest.main()
