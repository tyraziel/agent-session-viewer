import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import SessionPath
from agent_session_viewer.providers.claude import ClaudeProvider


class ClaudeDiscoveryTests(unittest.TestCase):
    def test_recursive_path_finds_nested_claude_transcript(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "case" / "transcripts"
            nested.mkdir(parents=True)
            transcript = nested / "session-123.jsonl"
            transcript.write_text(
                "\n".join([
                    json.dumps({
                        "type": "user",
                        "cwd": "/tmp/claude-project",
                        "sessionId": "session-123",
                        "message": {"role": "user", "content": "Hi"},
                    }),
                    json.dumps({
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "model": "claude-sonnet-5",
                            "content": [{"type": "text", "text": "Hello"}],
                        },
                    }),
                ]),
                encoding="utf-8",
            )
            provider = ClaudeProvider()

            shallow = provider.discover_projects([
                SessionPath(root, recursive=False),
            ])
            recursive = provider.discover_projects([
                SessionPath(root, recursive=True),
            ])

        self.assertEqual(shallow, [])
        self.assertEqual(len(recursive), 1)
        self.assertEqual(recursive[0].sessions[0].session_id, "session-123")
        self.assertEqual(recursive[0].name, "-tmp-claude-project")

    def test_deduplicate_skips_identical_claude_transcripts(self):
        content = "\n".join([
            json.dumps({
                "type": "user",
                "cwd": "/tmp/claude-project",
                "message": {"role": "user", "content": "Hi"},
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                },
            }),
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for filename in ("session-a.jsonl", "session-b.jsonl"):
                directory = root / filename.removesuffix(".jsonl")
                directory.mkdir()
                (directory / filename).write_text(content, encoding="utf-8")

            duplicates = ClaudeProvider().discover_projects([
                SessionPath(root, recursive=True),
            ])
            projects = ClaudeProvider().discover_projects([
                SessionPath(root, recursive=True, deduplicate=True),
            ])

        self.assertEqual(len(duplicates[0].sessions), 2)
        self.assertEqual(len(projects), 1)
        self.assertEqual(len(projects[0].sessions), 1)
