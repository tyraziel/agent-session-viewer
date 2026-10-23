import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import SessionPath
from agent_session_viewer.providers.codex import CodexProvider


class CodexDiscoveryTests(unittest.TestCase):
    def test_discovery_accepts_hash_prefixed_rollout_filename(self):
        session_id = "01a0edd1-4968-7f61-8811-bf8b9ed7457d"
        filename = (
            "a153656bd5e8fefafb313b2f0a52f88836ebd36a8004fe33b898d543f623e177-"
            f"rollout-2026-09-29T11-38-31-{session_id}.jsonl"
        )
        entries = [
            {
                "type": "session_meta",
                "payload": {"session_id": session_id, "cwd": "/tmp/codex-project"},
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / filename
            session_path.write_text(
                "\n".join(json.dumps(entry) for entry in entries),
                encoding="utf-8",
            )

            projects = CodexProvider(
                include_default_memory=False,
            ).discover_projects([Path(temp_dir)])

        self.assertEqual(len(projects), 1)
        self.assertEqual(len(projects[0].sessions), 1)
        self.assertEqual(projects[0].sessions[0].session_id, session_id)
        self.assertEqual(projects[0].sessions[0].path.name, filename)

    def test_recursive_path_object_controls_nested_rollout_discovery(self):
        session_id = "01a0edd1-4968-7f61-8811-bf8b9ed7457d"
        filename = f"rollout-2026-09-29T11-38-31-{session_id}.jsonl"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "case" / "artifacts"
            nested.mkdir(parents=True)
            (nested / filename).write_text(
                json.dumps({
                    "type": "session_meta",
                    "payload": {"session_id": session_id, "cwd": "/tmp/project"},
                }),
                encoding="utf-8",
            )
            provider = CodexProvider(include_default_memory=False)

            shallow = provider.discover_projects([
                SessionPath(root, recursive=False),
            ])
            recursive = provider.discover_projects([
                SessionPath(root, recursive=True),
            ])

        self.assertEqual(shallow, [])
        self.assertEqual(recursive[0].sessions[0].session_id, session_id)

    def test_deduplicate_skips_identical_rollout_files(self):
        session_id = "01a0edd1-4968-7f61-8811-bf8b9ed7457d"
        content = json.dumps({
            "type": "session_meta",
            "payload": {"session_id": session_id, "cwd": "/tmp/project"},
        })
        filename = f"rollout-2026-09-29T11-38-31-{session_id}.jsonl"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for folder in ("copy-a", "copy-b"):
                directory = root / folder
                directory.mkdir()
                (directory / filename).write_text(content, encoding="utf-8")

            duplicates = CodexProvider(
                include_default_memory=False,
            ).discover_projects([
                SessionPath(root, recursive=True),
            ])
            projects = CodexProvider(include_default_memory=False).discover_projects([
                SessionPath(root, recursive=True, deduplicate=True),
            ])

        self.assertEqual(len(duplicates[0].sessions), 2)
        self.assertEqual(len(projects), 1)
        self.assertEqual(len(projects[0].sessions), 1)


if __name__ == "__main__":
    unittest.main()
