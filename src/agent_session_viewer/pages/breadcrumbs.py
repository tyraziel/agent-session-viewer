"""Shared breadcrumb navigation for project/session pages.

Replaces the single back-arrow with a full trail so the user can jump back
to any ancestor level (Projects, then a specific project, etc.) without
stepping through intermediate pages.
"""

from nicegui import ui


def render_breadcrumbs(
    items: list[tuple[str, str | None]],
) -> tuple[ui.row, ui.label | None]:
    """Render a breadcrumb trail.

    :param items: ordered list of ``(label, path)``. A ``path`` of ``None``
        marks the **current** page, rendered as plain (non-clickable) text.
        Every other item is a clickable crumb that SPA-navigates to its path
        via ``ui.navigate.to`` (consistent with the rest of the app, so no
        full page reload and no anchor jump).

    :returns: the row element and the current-page label (or ``None`` if
        every item has a path). Callers may update the label's text later,
        e.g. once an async load has resolved a nicer title.
    """
    current: ui.label | None = None
    with ui.row().classes("items-center gap-1 w-full min-w-0") as row:
        for i, (label, path) in enumerate(items):
            if i:
                ui.label("›").classes("text-grey-7 text-sm select-none")
            if path is None:
                current = ui.label(label).classes(
                    "text-sm font-semibold text-grey-3 truncate"
                ).style("max-width: 460px;")
            else:
                crumb = ui.label(label).classes(
                    "text-sm text-grey-5 hover:text-primary "
                    "cursor-pointer transition-colors truncate"
                ).style("max-width: 340px;")
                crumb.on("click", lambda p=path: ui.navigate.to(p))
    return row, current
