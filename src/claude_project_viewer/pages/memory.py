"""Memory viewer page — browse project-level Claude Code memories."""

from pathlib import Path

from nicegui import run, ui

from claude_project_viewer.discovery import get_claude_base_dir


def create_memory_page(project_name: str, provider: str = "claude"):
    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(
                    f"/{provider}/project/{project_name}"
                ),
            ).props("dense flat")
            ui.label("Memory").classes("text-2xl font-bold")
            ui.space()
            ui.label(project_name).classes("text-sm text-grey-6").style(
                "font-family: monospace"
            )

        container = ui.column().classes("w-full gap-3")

    async def load():
        if provider != "claude":
            container.clear()
            with container:
                ui.label(
                    "Memory browsing is only available for Claude projects."
                ).classes("text-grey-6")
            return
        memories = await run.io_bound(_discover_memories, project_name)
        container.clear()
        with container:
            if not memories:
                ui.label("No memories found for this project.").classes("text-grey-6")
                return

            type_groups: dict[str, list[dict]] = {}
            for mem in memories:
                t = mem.get("type", "other")
                type_groups.setdefault(t, []).append(mem)

            type_icons = {
                "user": ("person", "primary"),
                "feedback": ("feedback", "amber"),
                "project": ("folder_special", "green"),
                "reference": ("link", "blue"),
            }

            for mem_type, mems in type_groups.items():
                icon_name, color = type_icons.get(mem_type, ("notes", "grey"))
                ui.label(mem_type.capitalize()).classes("text-lg font-bold mt-2")

                for mem in mems:
                    _render_memory_card(mem, icon_name, color)

    ui.timer(0.1, load, once=True)


def _render_memory_card(mem: dict, icon_name: str, color: str):
    name = mem.get("name", mem.get("filename", ""))
    description = mem.get("description", "")
    body = mem.get("body", "")

    with ui.card().classes("w-full").style(
        f"border-left: 3px solid var(--q-{color}); padding: 12px 16px;"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon_name).classes(f"text-{color}")
            ui.label(name).classes("font-bold text-sm")
        if description:
            ui.label(description).classes("text-xs text-grey-5 mt-1")
        if body:
            ui.html(
                f'<pre style="white-space: pre-wrap; word-break: break-word; '
                f"margin: 4px 0 0 0; font-size: 0.8rem; max-height: 300px; "
                f'overflow-y: auto;">{_escape_html(body)}</pre>'
            ).classes("mt-1")


def _discover_memories(project_name: str) -> list[dict]:
    base = get_claude_base_dir()
    memory_dir = base / "projects" / project_name / "memory"
    if not memory_dir.is_dir():
        return []

    memories = []
    for f in sorted(memory_dir.iterdir()):
        if f.suffix == ".md" and f.name != "MEMORY.md" and f.is_file():
            mem = _parse_memory_file(f)
            if mem:
                memories.append(mem)
    return memories


def _parse_memory_file(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta = {"filename": path.stem}

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()
            for line in frontmatter.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            meta["body"] = body
        else:
            meta["body"] = text
    else:
        meta["body"] = text

    return meta


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
