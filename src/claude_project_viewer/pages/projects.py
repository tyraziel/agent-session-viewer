"""Project listing page — browse all Claude Code projects."""

import time

from nicegui import run, ui

from claude_project_viewer.discovery import (
    PROVIDER_COLORS,
    ActiveSessionInfo,
    ProjectInfo,
    SessionInfo,
    discover_active_sessions,
    discover_all_projects,
    discover_history,
)
from claude_project_viewer.formatting import (
    format_duration_ago,
    format_size,
    get_activity_indicator,
)
from claude_project_viewer.providers import get_all_providers


def create_projects_page():
    state = {"projects": [], "last_mtimes": {}}

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-4 w-full"):
            ui.label("Session Viewer").classes("text-2xl font-bold")
            ui.space()

            async def _refresh():
                await _load_projects(state, container, filter_input, state.get("provider_select"))

            ui.button("Refresh", icon="refresh", on_click=_refresh).props(
                "dense outline"
            )

        active_container = ui.column().classes("w-full gap-2")

        history_container = ui.row().classes("w-full")

        with ui.row().classes("w-full gap-2 items-end"):
            filter_input = ui.input(
                label="Filter projects",
                placeholder="Type to filter...",
            ).classes("flex-grow")
            provider_options = {"all": "All"}
            for prov in get_all_providers():
                provider_options[prov.slug] = prov.name
            provider_select = ui.select(
                options=provider_options,
                value="all",
                label="Provider",
            ).classes("w-32")

        state["provider_select"] = provider_select

        def _on_filter_change():
            _apply_filter(
                state["projects"], container, filter_input, provider_select,
            )

        filter_input.on("update:model-value", _on_filter_change)
        provider_select.on("update:model-value", _on_filter_change)

        with ui.row().classes("w-full gap-2"):
            stats_label = ui.label("").classes("text-xs text-grey-6")

        container = ui.column().classes("w-full gap-2")

    async def _load_active(projects):
        active = await run.io_bound(discover_active_sessions, projects)
        active_container.clear()
        if active:
            with active_container:
                ui.label("Active Sessions").classes("text-lg font-bold")
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    for a in active:
                        _render_active_card(a)

    async def _initial_load():
        await _load_projects(state, container, filter_input, provider_select)
        total_projects = len(state["projects"])
        total_sessions = sum(p.session_count for p in state["projects"])
        stats_label.text = f"{total_projects} projects, {total_sessions} sessions"

        await _load_active(state["projects"])

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
                            ui.label("Claude Conversation History").classes(
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
            await _load_projects(state, container, filter_input, provider_select)
            await _load_active(state["projects"])

    ui.timer(0.1, _initial_load, once=True)
    ui.timer(5.0, _poll_changes)


async def _load_projects(state, container, filter_input, provider_select):
    projects = await run.io_bound(discover_all_projects)
    if projects is None:
        return
    state["projects"] = projects

    for project in projects:
        for session in project.sessions:
            state["last_mtimes"][str(session.path)] = session.mtime

    _apply_filter(projects, container, filter_input, provider_select)


def _apply_filter(projects, container, filter_input, provider_select=None):
    pattern = (filter_input.value or "").strip().lower()
    provider_filter = (provider_select.value if provider_select else "all") or "all"
    filtered = projects
    if provider_filter != "all":
        filtered = [p for p in filtered if p.provider == provider_filter]
    if pattern:
        filtered = [p for p in filtered if pattern in p.name.lower()]

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
    provider = project.provider
    badge_color = PROVIDER_COLORS.get(provider, "grey")

    with ui.card().classes("w-full cursor-pointer").on(
        "click", lambda p=project: ui.navigate.to(
            f"/{p.provider}/project/{p.name}"
        )
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
                with ui.row().classes("items-center gap-2"):
                    ui.label(project.name).classes("font-bold text-sm")
                    ui.badge(provider, color=badge_color).classes("text-xs")
                with ui.row().classes("gap-4"):
                    ui.label(
                        f"{project.session_count} session{'s' if project.session_count != 1 else ''}"
                    ).classes("text-xs text-grey-6")
                    ui.label(f"Project File Size: {format_size(total_size)}").classes("text-xs text-grey-6")
                    if latest_session:
                        ago = format_duration_ago(latest_session.mtime)
                        ui.label(f"Last active: {ago}").classes("text-xs text-grey-6")

            ui.icon("chevron_right").classes("text-grey-6")


def _truncate(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _render_active_card(active: ActiveSessionInfo):
    s = active.session
    project = active.project_name
    activity = get_activity_indicator(s.mtime)

    provider = s.provider
    badge_color = PROVIDER_COLORS.get(provider, "grey")
    url = f"/{provider}/project/{project}/session/{s.session_id}"
    with ui.card().classes("cursor-pointer").style(
        "background: #0a0a0a; border: 1px solid #1a3a1a; "
        "min-width: 340px; max-width: 480px; height: 220px; "
        "padding: 12px 16px; overflow: hidden;"
    ).on("click", lambda u=url: ui.navigate.to(u)):
        with ui.row().classes("items-center gap-2 w-full"):
            if activity:
                color, icon = activity
                ui.icon(icon).classes(f"text-{color} text-sm animate-pulse")
            ui.icon("terminal").classes("text-sm").style("color: #00ff41;")
            title = s.title or s.session_id[:12]
            ui.label(title).classes("text-sm font-bold").style(
                "color: #00ff41; font-family: monospace;"
            )
            ui.badge(provider, color=badge_color).classes("text-xs")

        with ui.row().classes("items-center gap-3"):
            ui.label(project).classes("text-xs text-grey-7").style(
                "font-family: monospace;"
            )
            ago = format_duration_ago(s.mtime)
            ui.label(ago).classes("text-xs text-grey-8")

        if active.exchanges:
            with ui.column().classes("w-full gap-1 mt-2").style(
                "overflow-y: auto; flex: 1;"
            ):
                for user_text, assistant_text in active.exchanges:
                    if user_text:
                        with ui.row().classes("items-start gap-1").style(
                            "border-left: 2px solid #00ff41; padding-left: 8px;"
                        ):
                            ui.label("$").classes("text-xs").style(
                                "color: #00ff41; font-family: monospace;"
                            )
                            ui.label(_truncate(user_text, 80)).classes(
                                "text-xs"
                            ).style("color: #b0b0b0; font-family: monospace;")
                    if assistant_text:
                        with ui.row().classes("items-start gap-1").style(
                            "border-left: 2px solid #333; padding-left: 8px;"
                        ):
                            ui.label(">").classes("text-xs").style(
                                "color: #666; font-family: monospace;"
                            )
                            ui.label(_truncate(assistant_text, 100)).classes(
                                "text-xs"
                            ).style("color: #808080; font-family: monospace;")
