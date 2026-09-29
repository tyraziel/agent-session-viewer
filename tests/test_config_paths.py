import json
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.config import load_config, resolve_provider_paths


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

        self.assertEqual(paths, [database])


if __name__ == "__main__":
    unittest.main()
