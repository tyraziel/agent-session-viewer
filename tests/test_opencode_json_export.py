import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import SessionPath
from agent_session_viewer.providers.opencode import OpencodeProvider, _resolve_dbs


def _export_payload(directory: str) -> dict:
    return {
        "info": {
            "id": "ses_export123",
            "title": "Exported OpenCode session",
            "directory": directory,
            "model": {
                "id": "gpt-6-luna",
                "providerID": "openai",
                "variant": "high",
            },
            "tokens": {
                "input": 1_000,
                "output": 80,
                "reasoning": 20,
                "cache": {"read": 100, "write": 10},
            },
            "time": {"created": 1_700_000_000_000, "updated": 1_700_000_010_000},
        },
        "messages": [
            {
                "info": {
                    "id": "message-user",
                    "role": "user",
                    "sessionID": "ses_export123",
                    "time": {"created": 1_700_000_000_000},
                },
                "parts": [{"id": "part-user", "type": "text", "text": "Run a check"}],
            },
            {
                "info": {
                    "id": "message-assistant",
                    "role": "assistant",
                    "sessionID": "ses_export123",
                    "modelID": "gpt-6-luna",
                    "providerID": "openai",
                    "tokens": {
                        "input": 1_000,
                        "output": 80,
                        "reasoning": 20,
                        "total": 1_100,
                        "cache": {"read": 100, "write": 10},
                    },
                    "time": {"created": 1_700_000_001_000},
                },
                "parts": [
                    {
                        "id": "part-reasoning",
                        "type": "reasoning",
                        "text": "Checking the request.",
                    },
                    {
                        "id": "part-tool",
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call-1",
                        "state": {
                            "status": "completed",
                            "input": {"command": "true"},
                            "output": "ok",
                        },
                    },
                    {"id": "part-text", "type": "text", "text": "Done."},
                ],
            },
        ],
    }


class OpencodeJsonExportTests(unittest.TestCase):
    def test_export_discovery_and_parsing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "json-export-project"
            export_dir = root / "exports"
            project_dir.mkdir()
            export_dir.mkdir()
            export_path = export_dir / "hash-ses_export123.json"
            export_path.write_text(
                json.dumps(_export_payload(str(project_dir))),
                encoding="utf-8",
            )
            provider = OpencodeProvider()

            projects = provider.discover_projects([export_dir])
            session = provider.parse_session(export_path, "ses_export123")
            exchanges = provider.extract_tail_exchanges(
                export_path, session_id="ses_export123",
            )

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "json-export-project")
        self.assertEqual(projects[0].sessions[0].session_id, "ses_export123")
        self.assertEqual(projects[0].sessions[0].title, "Exported OpenCode session")
        self.assertEqual(projects[0].sessions[0].turn_count, 1)
        self.assertEqual(projects[0].sessions[0].api_call_count, 1)

        self.assertEqual(session.model, "openai/gpt-6-luna")
        self.assertEqual(session.metadata["source_format"], "json_export")
        self.assertEqual(session.total_tokens["input_tokens"], 1_000)
        self.assertEqual(session.total_tokens["reasoning_tokens"], 20)
        self.assertEqual(session.total_tokens["cache_read_input_tokens"], 100)
        self.assertEqual(session.total_tokens["cache_creation_input_tokens"], 10)
        self.assertEqual(
            exchanges,
            [("Run a check", "Done.")],
        )

    def test_recursive_path_controls_nested_json_export_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "case" / "exports"
            nested.mkdir(parents=True)
            export_path = nested / "hash-ses_export123.json"
            export_path.write_text(
                json.dumps(_export_payload("/workspace/json-export-project")),
                encoding="utf-8",
            )
            provider = OpencodeProvider()

            shallow = provider.discover_projects([
                SessionPath(root, recursive=False),
            ])
            recursive = provider.discover_projects([
                SessionPath(root, recursive=True),
            ])

        self.assertEqual(shallow, [])
        self.assertEqual(recursive[0].sessions[0].session_id, "ses_export123")

    def test_recursive_path_controls_nested_database_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "case" / "dbs"
            nested.mkdir(parents=True)
            db_path = nested / "opencode.db"
            with sqlite3.connect(db_path) as db:
                db.execute("create table session (id text)")
                db.execute("create table message (id text)")
                db.execute("create table part (id text)")

            shallow = _resolve_dbs([SessionPath(root, recursive=False)])
            recursive = _resolve_dbs([SessionPath(root, recursive=True)])

        self.assertEqual(shallow, [])
        self.assertEqual(recursive, [db_path])

    def test_deduplicate_skips_identical_database_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_dir = root / "copy-a"
            second_dir = root / "copy-b"
            first_dir.mkdir()
            second_dir.mkdir()
            first_db = first_dir / "opencode.db"
            second_db = second_dir / "opencode-copy.db"
            with sqlite3.connect(first_db) as db:
                db.execute("create table session (id text)")
                db.execute("create table message (id text)")
                db.execute("create table part (id text)")
            second_db.write_bytes(first_db.read_bytes())

            duplicates = _resolve_dbs([
                SessionPath(root, recursive=True),
            ])
            databases = _resolve_dbs([
                SessionPath(root, recursive=True, deduplicate=True),
            ])

        self.assertEqual(len(duplicates), 2)
        self.assertEqual(len(databases), 1)


if __name__ == "__main__":
    unittest.main()
