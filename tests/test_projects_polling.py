import unittest
from unittest.mock import AsyncMock, patch

from agent_session_viewer.pages.projects import _load_active, _load_projects


class _DeletedClient:
    is_deleted = True


class _Container:
    def clear(self):
        raise AssertionError("stale clients must not mutate page elements")


class ProjectsPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_projects_skips_ui_updates_after_client_deletion(self):
        state = {}
        with patch(
            "agent_session_viewer.pages.projects.run.io_bound",
            new=AsyncMock(return_value=[]),
        ):
            loaded = await _load_projects(
                state,
                _Container(),
                None,
                None,
                _DeletedClient(),
            )

        self.assertFalse(loaded)
        self.assertEqual(state, {})

    async def test_load_active_skips_ui_updates_after_client_deletion(self):
        with patch(
            "agent_session_viewer.pages.projects.run.io_bound",
            new=AsyncMock(return_value=[]),
        ):
            await _load_active([], _Container(), _DeletedClient())


if __name__ == "__main__":
    unittest.main()
