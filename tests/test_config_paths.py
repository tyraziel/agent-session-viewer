import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import (
    SessionPath,
    load_config,
    resolve_provider_paths,
)


class ConfigPathTests(unittest.TestCase):
    def test_existing_database_file_is_not_logged_as_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "opencode.db"
            database.touch()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "opencode": {
                            "session_paths": [str(database)],
                            "include_default": False,
                        },
                    },
                }),
                encoding="utf-8",
            )
            config = load_config(config_path)

            with self.assertNoLogs("agent_session_viewer", level="WARNING"):
                paths = resolve_provider_paths(config, "opencode", [])

        self.assertEqual(paths, [SessionPath(database)])

    def test_object_path_requires_path_and_defaults_recursive_to_false(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir = root / "sessions"
            session_dir.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "codex": {
                            "session_paths": [
                                {"path": str(session_dir)},
                                {"recursive": True},
                            ],
                            "include_default": False,
                        },
                    },
                }),
                encoding="utf-8",
            )

            with self.assertLogs("agent_session_viewer", level="WARNING"):
                paths = resolve_provider_paths(
                    load_config(config_path), "codex", [],
                )

        self.assertEqual(paths, [SessionPath(session_dir, recursive=False)])

    def test_object_path_accepts_recursive_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir = root / "sessions"
            session_dir.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "codex": {
                            "session_paths": [{
                                "path": str(session_dir),
                                "recursive": True,
                            }],
                            "include_default": False,
                        },
                    },
                }),
                encoding="utf-8",
            )

            paths = resolve_provider_paths(
                load_config(config_path), "codex", [],
            )

        self.assertEqual(paths, [SessionPath(session_dir, recursive=True)])

    def test_object_path_deduplicate_defaults_to_false(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir = root / "sessions"
            session_dir.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "codex": {
                            "session_paths": [{
                                "path": str(session_dir),
                                "recursive": True,
                            }],
                            "include_default": False,
                        },
                    },
                }),
                encoding="utf-8",
            )

            paths = resolve_provider_paths(
                load_config(config_path), "codex", [],
            )

        self.assertEqual(
            paths,
            [SessionPath(session_dir, recursive=True, deduplicate=False)],
        )

    def test_object_path_accepts_deduplicate_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir = root / "sessions"
            session_dir.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({
                    "providers": {
                        "codex": {
                            "session_paths": [{
                                "path": str(session_dir),
                                "deduplicate": True,
                            }],
                            "include_default": False,
                        },
                    },
                }),
                encoding="utf-8",
            )

            paths = resolve_provider_paths(
                load_config(config_path), "codex", [],
            )

        self.assertEqual(
            paths,
            [SessionPath(session_dir, recursive=False, deduplicate=True)],
        )


if __name__ == "__main__":
    unittest.main()
