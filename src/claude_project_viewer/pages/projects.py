"""Project listing page — browse all Claude Code projects."""

import time

from nicegui import run, ui

from claude_project_viewer.discovery import (
    ProjectInfo,
    SessionInfo,
    discover_history,
    discover_projects,
)
from claude_project_viewer.formatting import (
    format_duration_ago,
    format_size,
    get_activity_indicator,
)


def create_projects_page():
    state = {"projects": [], "last_mtimes": {}}

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-4 w-full"):
            ui.label("Claude Project Viewer").classes("text-2xl font-bold")
            ui.space()

            async def _refresh():
                await _load_projects(state, container, filter_input)

            ui.button("Refresh", icon="refresh", on_click=_refresh).props(
                "dense outline"
            )

        history_container = ui.row().classes("w-full")

        filter_input = ui.input(
            label="Filter projects",
            placeholder="Type to filter...",
        ).classes("w-full")
        filter_input.on("update:model-value", lambda: _apply_filter(
            state["projects"], container, filter_input
        ))

        with ui.row().classes("w-full gap-2"):
            stats_label = ui.label("").classes("text-xs text-grey-6")

        container = ui.column().classes("w-full gap-2")

    async def _initial_load():
        await _load_projects(state, container, filter_input)
        total_projects = len(state["projects"])
        total_sessions = sum(p.session_count for p in state["projects"])
        stats_label.text = f"{total_projects} projects, {total_sessions} sessions"

        history = await run.io_bound(discover_history)
        history_container.clear()
        if history:
            with history_container:
                with ui.card().classes("w-full cursor-pointer").on(
                    "click", lambda: ui.navigate.to("/history")
                ):
                    with ui.row().classes("items-center gap-3 w-full"):
                        ui.icon("history").classes("text-amber text-lg")
                        with ui.column().classes("gap-0 flex-grow"):
                            ui.label("Conversation History").classes(
                                "font-bold text-sm"
                            )
                            with ui.row().classes("gap-4"):
                                ui.label("~/.claude/history.jsonl").classes(
                                    "text-xs text-grey-6"
                                ).style("font-family: monospace")
                                ui.label(format_size(history.size_bytes)).classes(
                                    "text-xs text-grey-6"
                                )
                                ago = format_duration_ago(history.mtime)
                                ui.label(f"Last updated: {ago}").classes(
                                    "text-xs text-grey-6"
                                )
                        ui.icon("chevron_right").classes("text-grey-6")

    async def _poll_changes():
        if ui.context.client.is_deleted:
            return
        changed = False
        for project in state["projects"]:
            for session in project.sessions:
                key = str(session.path)
                try:
                    current_mtime = session.path.stat().st_mtime
                except OSError:
                    continue
                if state["last_mtimes"].get(key) != current_mtime:
                    state["last_mtimes"][key] = current_mtime
                    changed = True
        if changed:
            await _load_projects(state, container, filter_input)

    ui.timer(0.1, _initial_load, once=True)
    ui.timer(5.0, _poll_changes)


async def _load_projects(state, container, filter_input):
    projects = await run.io_bound(discover_projects)
    state["projects"] = projects

    for project in projects:
        for session in project.sessions:
            state["last_mtimes"][str(session.path)] = session.mtime

    _apply_filter(projects, container, filter_input)


def _apply_filter(projects, container, filter_input):
    pattern = (filter_input.value or "").strip().lower()
    filtered = projects
    if pattern:
        filtered = [p for p in projects if pattern in p.name.lower()]

    container.clear()
    with container:
        if not filtered:
            ui.label("No projects found.").classes("text-grey-6")
            return
        for project in filtered:
            _render_project_card(project)


def _render_project_card(project: ProjectInfo):
    latest_session = project.sessions[0] if project.sessions else None
    total_size = sum(s.size_bytes for s in project.sessions)

    with ui.card().classes("w-full cursor-pointer").on(
        "click", lambda p=project: ui.navigate.to(f"/project/{p.name}")
    ):
        with ui.row().classes("items-center gap-3 w-full"):
            latest = project.sessions[0] if project.sessions else None
            activity = get_activity_indicator(latest.mtime) if latest else None
            if activity:
                color, icon = activity
                ui.icon(icon).classes(f"text-{color} text-lg animate-pulse")
            else:
                ui.icon("folder").classes("text-primary text-lg")
            with ui.column().classes("gap-0 flex-grow"):
                ui.label(project.name).classes("font-bold text-sm")
                with ui.row().classes("gap-4"):
                    ui.label(
                        f"{project.session_count} session{'s' if project.session_count != 1 else ''}"
                    ).classes("text-xs text-grey-6")
                    ui.label(format_size(total_size)).classes("text-xs text-grey-6")
                    if latest_session:
                        ago = format_duration_ago(latest_session.mtime)
                        ui.label(f"Last active: {ago}").classes("text-xs text-grey-6")

            ui.icon("chevron_right").classes("text-grey-6")
