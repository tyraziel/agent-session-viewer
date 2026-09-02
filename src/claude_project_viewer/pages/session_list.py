"""Session list page for a specific project."""

from nicegui import run, ui

from claude_project_viewer.discovery import discover_all_projects
from claude_project_viewer.formatting import (
    format_duration_ago,
    format_size,
    get_activity_indicator,
)


def create_session_list_page(project_name: str, provider: str = "claude"):
    state = {"sessions": []}

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "dense flat"
            )
            ui.label(project_name).classes("text-2xl font-bold")
            ui.space()
            ui.button(
                "Memory", icon="psychology",
                on_click=lambda: ui.navigate.to(
                    f"/{provider}/project/{project_name}/memory"
                ),
            ).props("dense outline")

        stats_label = ui.label("").classes("text-xs text-grey-6")
        container = ui.column().classes("w-full gap-2")

        async def load():
            projects = await run.io_bound(discover_all_projects)
            project = next(
                (p for p in projects
                 if p.name == project_name and p.provider == provider),
                None,
            )
            if not project:
                container.clear()
                with container:
                    ui.label("Project not found.").classes("text-red")
                return

            state["sessions"] = project.sessions
            _render(project.sessions, container, stats_label, provider, project_name)

        ui.timer(0.1, load, once=True)


def _render(sessions, container, stats_label, provider, project_name):
    total = len(sessions)
    stats_label.text = f"{total} session{'s' if total != 1 else ''}"

    container.clear()
    with container:
        if not sessions:
            ui.label("No sessions found.").classes("text-grey-6")
            return

        for session in sessions:
            ago = format_duration_ago(session.mtime)
            size = format_size(session.size_bytes)

            with ui.card().classes("w-full cursor-pointer").on(
                "click",
                lambda s=session, pn=project_name, pv=provider: ui.navigate.to(
                    f"/{pv}/project/{pn}/session/{s.session_id}"
                ),
            ):
                with ui.row().classes("items-center gap-3 w-full"):
                    activity = get_activity_indicator(session.mtime)
                    if activity:
                        color, icon = activity
                        ui.icon(icon).classes(f"text-{color} text-lg animate-pulse")
                    else:
                        ui.icon("chat").classes("text-grey-6 text-lg")
                    with ui.column().classes("gap-0 flex-grow"):
                        if session.title:
                            with ui.row().classes("items-center gap-2"):
                                ui.label(session.title).classes("font-bold text-sm")
                                if session.turn_count > 0:
                                    ui.badge(
                                        f"{session.turn_count} turn{'s' if session.turn_count != 1 else ''}",
                                        color="primary",
                                    ).classes("text-xs")
                                if session.api_call_count > 0:
                                    ui.badge(
                                        f"{session.api_call_count} API call{'s' if session.api_call_count != 1 else ''}",
                                        color="grey",
                                    ).classes("text-xs")
                            ui.label(session.session_id).classes(
                                "text-xs text-grey-5"
                            ).style("font-family: monospace")
                        else:
                            with ui.row().classes("items-center gap-2"):
                                ui.label(session.session_id).classes(
                                    "font-bold text-sm"
                                ).style("font-family: monospace")
                                if session.turn_count > 0:
                                    ui.badge(
                                        f"{session.turn_count} turn{'s' if session.turn_count != 1 else ''}",
                                        color="primary",
                                    ).classes("text-xs")
                                if session.api_call_count > 0:
                                    ui.badge(
                                        f"{session.api_call_count} API call{'s' if session.api_call_count != 1 else ''}",
                                        color="grey",
                                    ).classes("text-xs")
                        with ui.row().classes("gap-4 items-center"):
                            ui.label(f"Session File Size: {size}").classes("text-xs text-grey-6")
                            ui.label(f"Last Active: {ago}").classes("text-xs text-grey-6")
                        cmd = session.resume_command
                        with ui.row().classes("items-center gap-1 mt-1"):
                            ui.label(cmd).classes("text-xs text-grey-5").style(
                                "font-family: monospace; user-select: all;"
                            )
                            ui.button(
                                icon="content_copy",
                                on_click=lambda c=cmd: ui.run_javascript(
                                    f"navigator.clipboard.writeText({c!r})"
                                ),
                            ).props("dense flat size=xs").classes("text-grey-6")
                    ui.icon("chevron_right").classes("text-grey-6")
