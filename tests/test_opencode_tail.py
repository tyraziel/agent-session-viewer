import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_session_viewer.providers.opencode import OpencodeProvider


class OpencodeTailTests(unittest.TestCase):
    def test_sqlite_tail_keeps_last_assistant_text_per_user_exchange(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE message (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    time_created INTEGER,
                    data TEXT
                );
                CREATE TABLE part (
                    id TEXT PRIMARY KEY,
                    message_id TEXT,
                    data TEXT
                );
                """
            )
            messages = [
                ("m1", 1, "user", "First prompt"),
                ("m2", 2, "assistant", "First reply before tool"),
                ("m3", 3, "assistant", "First final reply"),
                ("m4", 4, "user", "Second prompt"),
                ("m5", 5, "assistant", "Second reply before tool"),
                ("m6", 6, "assistant", "Second final reply"),
            ]
            for message_id, timestamp, role, text in messages:
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?, ?)",
                    (
                        message_id,
                        "session-1",
                        timestamp,
                        json.dumps({"role": role}),
                    ),
                )
                conn.execute(
                    "INSERT INTO part VALUES (?, ?, ?)",
                    (
                        f"p-{message_id}",
                        message_id,
                        json.dumps({"type": "text", "text": text}),
                    ),
                )
            conn.commit()
            conn.close()

            exchanges = OpencodeProvider().extract_tail_exchanges(
                path, session_id="session-1",
            )

        self.assertEqual(
            exchanges,
            [
                ("First prompt", "First final reply"),
                ("Second prompt", "Second final reply"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
