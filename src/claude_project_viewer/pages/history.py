"""History page — browse ~/.claude/history.jsonl (prompt history log)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from nicegui import run, ui

from claude_project_viewer.discovery import discover_history
from claude_project_viewer.formatting import format_duration_ago, format_size


def create_history_page():
    state = {"entries": [], "last_mtime": 0.0, "history_path": None}

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
                "dense flat"
            )
            header_label = ui.label("Conversation History").classes(
                "text-2xl font-bold"
            )
            ui.space()

            async def _refresh():
                await _load(state, meta_row, filter_input, container)

            ui.button("Refresh", icon="refresh", on_click=_refresh).props(
                "dense outline"
            )

        meta_row = ui.row().classes("items-center gap-4")

        with ui.row().classes("items-end gap-4 w-full"):
            filter_input = ui.input(
                label="Filter prompts",
                placeholder="Type to filter...",
            ).classes("flex-grow")

            project_select = ui.select(
                options={"": "All Projects"},
                value="",
                label="Project",
            ).classes("w-64")

            limit_select = ui.select(
                options={10: "10", 50: "50", 100: "100", 150: "150", 200: "200"},
                value=50,
                label="Show",
            ).classes("w-24")

        container = ui.column().classes("w-full gap-1")

    async def _load(state, meta_row, filter_input, container):
        history = await run.io_bound(discover_history)
        if not history:
            header_label.text = "No history.jsonl found"
            return

        state["history_path"] = history.path
        state["last_mtime"] = history.mtime

        entries = await run.io_bound(_read_history, history.path)
        state["entries"] = entries

        projects = sorted({e.get("project", "") for e in entries if e.get("project")})
        options = {"": "All Projects"}
        for p in projects:
            short = p.rsplit("/", 1)[-1] if "/" in p else p
            options[p] = short
        current = project_select.value
        project_select.options = options
        if current not in options:
            project_select.value = ""
        project_select.update()

        meta_row.clear()
        with meta_row:
            ui.badge(f"{len(entries)} prompts", color="primary").classes("text-xs")
            ui.label(format_size(history.size_bytes)).classes("text-xs text-grey-6")
            ago = format_duration_ago(history.mtime)
            ui.label(f"Last updated: {ago}").classes("text-xs text-grey-6")

        _render_entries(entries, container, filter_input, project_select, limit_select)

    def _on_filter_change():
        _render_entries(state["entries"], container, filter_input, project_select, limit_select)

    filter_input.on("update:model-value", _on_filter_change)
    project_select.on("update:model-value", _on_filter_change)
    limit_select.on("update:model-value", _on_filter_change)

    async def _initial_load():
        await _load(state, meta_row, filter_input, container)

    async def poll():
        if ui.context.client.is_deleted:
            return
        path = state["history_path"]
        if path is None:
            return
        try:
            current_mtime = Path(path).stat().st_mtime
        except OSError:
            return
        if current_mtime != state["last_mtime"]:
            await _load(state, meta_row, filter_input, container)

    ui.timer(0.1, _initial_load, once=True)
    ui.timer(5.0, poll)


def _read_history(path: Path) -> list[dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _render_entries(entries, container, filter_input, project_select, limit_select):
    pattern = (filter_input.value or "").strip().lower()
    project_filter = project_select.value or ""
    limit = limit_select.value or 50

    filtered = entries
    if pattern:
        filtered = [
            e for e in filtered
            if pattern in (e.get("display", "") or "").lower()
        ]
    if project_filter:
        filtered = [e for e in filtered if e.get("project") == project_filter]

    total = len(filtered)
    display_entries = filtered[-limit:]

    container.clear()
    with container:
        if not filtered:
            ui.label("No matching entries.").classes("text-grey-6")
            return

        label = f"Prompts (showing {len(display_entries)} of {total})"
        ui.label(label).classes("text-lg font-bold")
        for entry in reversed(display_entries):
            _render_entry(entry)


def _project_path_to_slug(project_path: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]", "-", project_path)


def _render_entry(entry: dict):
    display = entry.get("display", "")
    project = entry.get("project", "")
    session_id = entry.get("sessionId", "")
    timestamp = entry.get("timestamp", 0)

    project_short = project.rsplit("/", 1)[-1] if "/" in project else project
    project_slug = _project_path_to_slug(project) if project else ""
    time_str = ""
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

    has_link = bool(project_slug and session_id)

    with ui.card().classes("w-full py-1 px-3"):
        with ui.row().classes("items-start gap-2 w-full"):
            ui.icon("person").classes("text-primary text-sm mt-1")
            with ui.column().classes("gap-0 flex-grow"):
                ui.html(
                    f'<pre style="white-space: pre-wrap; word-break: break-word; '
                    f'margin: 0; font-size: 0.8rem; max-height: 200px; '
                    f'overflow-y: auto;">{_escape_html(display)}</pre>'
                )
                with ui.row().classes("gap-3 mt-1 items-center"):
                    if project_short:
                        ui.label(project_short).classes("text-xs text-grey-6").style(
                            "font-family: monospace"
                        )
                    if time_str:
                        ui.label(time_str).classes("text-xs text-grey-6")
                    if has_link:
                        ui.button(
                            "View Session",
                            icon="open_in_new",
                            on_click=lambda slug=project_slug, sid=session_id: (
                                ui.navigate.to(f"/project/{slug}/session/{sid}")
                            ),
                        ).props("dense flat size=xs")


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
