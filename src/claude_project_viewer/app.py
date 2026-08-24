"""NiceGUI application — routes and dark theme."""

from pathlib import Path

from nicegui import app, ui

from claude_project_viewer.config import set_session_paths
from claude_project_viewer.pages.history import create_history_page
from claude_project_viewer.pages.memory import create_memory_page
from claude_project_viewer.pages.projects import create_projects_page
from claude_project_viewer.pages.session_detail import create_session_detail_page
from claude_project_viewer.pages.session_list import create_session_list_page


def _page_setup():
    ui.dark_mode(True)
    with ui.footer().classes("items-center justify-center").style(
        "background: #0a0a1a; border-top: 1px solid #2a2a4a; padding: 8px;"
    ):
        ui.html(
            'Cost estimates are based on '
            '<a href="https://www.anthropic.com/pricing" target="_blank" '
            'style="color: #9e9e9e; text-decoration: underline;">'
            'published Anthropic list prices</a>'
            ' as of August 20th, 2026 and may not reflect actual billing.'
        ).classes("text-xs text-grey-7")


def create_app(session_paths: list[Path] | None = None):
    if session_paths is not None:
        set_session_paths(session_paths)
    @ui.page("/")
    def index():
        _page_setup()
        create_projects_page()

    @ui.page("/history")
    def history():
        _page_setup()
        create_history_page()

    @ui.page("/project/{project_name}")
    def project_sessions(project_name: str):
        _page_setup()
        create_session_list_page(project_name)

    @ui.page("/project/{project_name}/memory")
    def project_memory(project_name: str):
        _page_setup()
        create_memory_page(project_name)

    @ui.page("/project/{project_name}/session/{session_id}")
    def session_detail(project_name: str, session_id: str):
        _page_setup()
        create_session_detail_page(project_name, session_id)
