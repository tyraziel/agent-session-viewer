"""Shared navigation controls for clickable cards."""

import json

from nicegui import ui


def open_in_new_tab_button(url: str):
    """Render a button that opens a card's target without bubbling its click."""
    button = ui.button(icon="open_in_new").props("dense flat size=xs")
    button.classes("text-grey-6")
    button.on(
        "click",
        js_handler=(
            "(event) => { event.stopPropagation(); "
            f"window.open({json.dumps(url)}, '_blank', 'noopener,noreferrer'); }}"
        ),
    )
    button.tooltip("Open in new tab")
    return button
