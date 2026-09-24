import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import load_config
from agent_session_viewer.providers.codex import CodexProvider


def _create_memory_db(
    path: Path,
    thread_id: str,
    raw_memory: str,
    rollout_summary: str,
    generated_at: int,
) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "create table stage1_outputs ("
            "thread_id text, raw_memory text, rollout_summary text, "
            "generated_at integer)"
        )
        db.execute(
            "insert into stage1_outputs values (?, ?, ?, ?)",
            (thread_id, raw_memory, rollout_summary, generated_at),
        )


class CodexMemoryTests(unittest.TestCase):
    def test_provider_reads_latest_memory_from_multiple_databases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older_db = root / "memories-older.sqlite"
            newer_db = root / "memories-newer.sqlite"
            _create_memory_db(
                older_db, "codex-thread", "older memory", "older summary", 1,
            )
            _create_memory_db(
                newer_db, "codex-thread", "newer memory", "newer summary", 2,
            )
            session_path = root / "rollout-test.jsonl"
            session_path.write_text(
                json.dumps({
                    "type": "session_meta",
                    "payload": {"session_id": "codex-thread"},
                }),
                encoding="utf-8",
            )

            session = CodexProvider(
                memory_paths=[older_db, newer_db],
                include_default_memory=False,
            ).parse_session(session_path)

        self.assertEqual(session.metadata["session_summary"], "newer summary")
        self.assertEqual(session.metadata["session_memory"], "newer memory")

    def test_provider_leaves_summary_metadata_empty_without_a_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            memory_db = root / "memories.sqlite"
            _create_memory_db(memory_db, "another-thread", "", "", 1)
            session_path = root / "rollout-test.jsonl"
            session_path.write_text(
                json.dumps({
                    "type": "session_meta",
                    "payload": {"session_id": "codex-thread"},
                }),
                encoding="utf-8",
            )

            session = CodexProvider(
                memory_paths=[memory_db],
                include_default_memory=False,
            ).parse_session(session_path)

        self.assertEqual(session.metadata, {})

    def test_config_accepts_multiple_codex_memory_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            configured_path = root / "extra-memories.sqlite"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "codex": {
                            "memory_paths": [
                                "~/custom/memories.sqlite",
                                str(configured_path),
                            ],
                            "include_default_memory": False,
                        },
                    },
                }),
                encoding="utf-8",
            )

            provider_config = load_config(config_path).providers["codex"]

        self.assertEqual(
            provider_config.memory_paths,
            [Path.home() / "custom/memories.sqlite", configured_path],
        )
        self.assertFalse(provider_config.include_default_memory)


if __name__ == "__main__":
    unittest.main()
