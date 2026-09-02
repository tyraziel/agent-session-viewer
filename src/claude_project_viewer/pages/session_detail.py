"""Session detail page — turn-by-turn conversation viewer."""

from pathlib import Path

from nicegui import run, ui

from claude_project_viewer.discovery import discover_all_projects
from claude_project_viewer.providers import get_provider
from claude_project_viewer.formatting import format_duration, format_duration_ago, get_activity_indicator
from claude_project_viewer.parser import Message, Session, SubAgentInfo, Turn, parse_session


def create_session_detail_page(
    project_name: str, session_id: str, provider: str = "claude",
):
    state = {"session": None, "last_mtime": 0.0, "session_path": None}
    expanded_turns: set[int] = set()

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(
                    f"/{provider}/project/{project_name}"
                ),
            ).props("dense flat")
            header_label = ui.label("Loading...").classes("text-2xl font-bold")

        meta_row = ui.row().classes("items-center gap-4")
        summary_container = ui.column().classes("w-full")

        with ui.row().classes("items-center gap-2 w-full"):
            ui.label("Turns").classes("text-lg font-bold")
            ui.space()
            turns_label = ui.label("").classes("text-xs text-grey-6")
            limit_select = ui.select(
                options={10: "10", 25: "25", 50: "50", 100: "100", 200: "200", 0: "All"},
                value=25,
                label="Show",
            ).classes("w-24")

        turns_container = ui.column().classes("w-full gap-1")

    async def load():
        projects = await run.io_bound(discover_all_projects)
        project = next(
            (p for p in projects
             if p.name == project_name and p.provider == provider),
            None,
        )
        if not project:
            header_label.text = "Project not found"
            return

        session_info = next(
            (s for s in project.sessions if s.session_id == session_id), None
        )
        if not session_info:
            header_label.text = "Session not found"
            return

        state["session_path"] = session_info.path
        state["resume_command"] = session_info.resume_command
        state["title"] = session_info.title
        state["provider"] = provider
        prov = get_provider(provider)
        parse_fn = prov.parse_session if prov else parse_session
        session = await run.io_bound(parse_fn, session_info.path)
        state["session"] = session
        state["last_mtime"] = session_info.mtime

        _render_session(
            session, header_label, meta_row, summary_container,
            turns_container, turns_label, expanded_turns, session_info.mtime,
            state["resume_command"], state["title"], limit_select,
        )

    async def poll():
        if ui.context.client.is_deleted:
            return
        path = state["session_path"]
        if path is None:
            return
        try:
            current_mtime = Path(path).stat().st_mtime
        except OSError:
            return
        if current_mtime != state["last_mtime"]:
            state["last_mtime"] = current_mtime
            prov = get_provider(state.get("provider", "claude"))
            parse_fn = prov.parse_session if prov else parse_session
            session = await run.io_bound(parse_fn, path)
            state["session"] = session
            _render_session(
                session, header_label, meta_row, summary_container,
                turns_container, turns_label, expanded_turns, current_mtime,
                state.get("resume_command", ""), state.get("title", ""),
                limit_select,
            )

    def _on_limit_change():
        session = state["session"]
        if session:
            _render_turns(
                session, turns_container, turns_label, expanded_turns, limit_select,
            )

    limit_select.on("update:model-value", _on_limit_change)

    ui.timer(0.1, load, once=True)
    ui.timer(3.0, poll)


def _get_turn_conversation(turn: Turn) -> list[tuple[str, str]]:
    """Extract all conversational messages (user prompts + assistant text) from a turn."""
    conversation = []
    for msg in turn.messages:
        if msg.role == "user" and msg.content:
            conversation.append(("user", msg.content))
        elif msg.role == "assistant" and msg.content:
            conversation.append(("assistant", msg.content))
    return conversation


def _render_session(
    session: Session,
    header_label,
    meta_row,
    summary_container,
    turns_container,
    turns_label,
    expanded_turns: set[int],
    mtime: float,
    resume_command: str = "",
    title: str = "",
    limit_select=None,
):
    model_display = session.model or "unknown"
    if title:
        header_label.text = f"{title} ({model_display})"
    else:
        header_label.text = f"Session ({model_display})"

    meta_row.clear()
    with meta_row:
        activity = get_activity_indicator(mtime)
        if activity:
            color, icon = activity
            ui.icon(icon).classes(f"text-{color} animate-pulse")
        total_tools = sum(
            len(tc) for turn in session.turns
            for m in turn.messages for tc in [m.tool_calls] if tc
        )
        ui.badge(f"{session.total_turns} turns", color="primary").classes("text-xs")
        ui.badge(f"{session.api_call_count} API calls", color="grey").classes("text-xs")
        if total_tools > 0:
            ui.badge(
                f"{total_tools} tool call{'s' if total_tools != 1 else ''}",
                color="orange",
            ).classes("text-xs")
        total_dur = session.total_duration_seconds
        if total_dur > 0:
            ui.badge(
                f"{format_duration(total_dur)} model time",
                color="blue-grey",
            ).classes("text-xs")
        ago = format_duration_ago(mtime)
        ui.label(f"Last active: {ago}").classes("text-xs text-grey-6")
        ui.label(session.session_id).classes("text-xs text-grey-6").style(
            "font-family: monospace"
        )
        if resume_command:
            ui.button(
                "Resume command", icon="content_copy",
                on_click=lambda: ui.run_javascript(
                    f"navigator.clipboard.writeText({resume_command!r})"
                ),
            ).props("dense flat size=xs").classes("text-grey-6")

    summary_container.clear()
    with summary_container:
        _render_token_summary(session)

    _render_turns(session, turns_container, turns_label, expanded_turns, limit_select)


def _render_turns(session, turns_container, turns_label, expanded_turns, limit_select):
    limit = limit_select.value if limit_select else 0
    all_turns = list(reversed(session.turns))
    total = len(all_turns)

    if limit and limit > 0:
        display = all_turns[:limit]
    else:
        display = all_turns

    turns_label.text = f"Showing {len(display)} of {total}"

    turns_container.clear()
    with turns_container:
        for turn in display:
            _render_turn_row(turn, expanded_turns)


def _format_cost(cost: float) -> str:
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _cost_label(cost: float):
    """Render a cost value in matrix green."""
    ui.label(_format_cost(cost)).classes("text-xs").style(
        "color: #00ff41; font-family: monospace;"
    )


def _render_token_summary(session: Session):
    tokens = session.total_tokens
    total = tokens["input_tokens"] + tokens["output_tokens"]
    cache_read = tokens["cache_read_input_tokens"]
    cache_create = tokens["cache_creation_input_tokens"]
    all_input = tokens["input_tokens"] + cache_read + cache_create
    cache_ratio = cache_read / all_input if all_input > 0 else 0.0
    subagent_tok = session.total_subagent_tokens
    total_cost = session.estimated_cost
    cost_by_type = session.cost_by_type

    if total == 0:
        return

    with ui.card().classes("w-full").style(
        "background: #1a1a2e; border: 1px solid #2a2a4a;"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.label("Token Summary").classes("text-sm font-bold")
            if total_cost > 0:
                ui.badge(
                    f"~{_format_cost(total_cost)}", color="green",
                ).classes("text-xs").tooltip(
                    "Estimated from published list prices. "
                    "Actual costs may differ due to negotiated rates, "
                    "billing tier, or pricing changes."
                )

        with ui.grid(columns=9).classes("gap-1"):
            ui.label("Input:").classes("text-xs text-grey-6")
            ui.label(f"{tokens['input_tokens']:,}").classes("text-xs")
            _cost_label(cost_by_type["input"])
            ui.label("Output:").classes("text-xs text-grey-6")
            ui.label(f"{tokens['output_tokens']:,}").classes("text-xs")
            _cost_label(cost_by_type["output"])
            ui.label("Total:").classes("text-xs text-grey-6")
            ui.label(f"{total:,}").classes("text-xs")
            _cost_label(total_cost)
            ui.label("Cache Read:").classes("text-xs text-grey-6")
            ui.label(f"{cache_read:,}").classes("text-xs")
            _cost_label(cost_by_type["cache_read"])
            ui.label("Cache Create:").classes("text-xs text-grey-6")
            ui.label(f"{cache_create:,}").classes("text-xs")
            _cost_label(cost_by_type["cache_create"])
            ui.label("Cache Hit:").classes("text-xs text-grey-6")
            ui.label(f"{cache_ratio:.1%}").classes("text-xs")
            ui.label("").classes("text-xs")
            if subagent_tok > 0:
                ui.label("Subagent:").classes("text-xs text-purple")
                ui.label(f"{subagent_tok:,}").classes("text-xs text-purple")
                ui.label("").classes("text-xs")


def _render_turn_row(turn: Turn, expanded_turns: set[int]):
    type_colors = {
        "system": "blue",
        "user": "primary",
        "assistant": "green",
        "tool_use": "orange",
        "agent": "purple",
        "unknown": "grey",
    }
    turn_type = turn.turn_type
    color = type_colors.get(turn_type, "grey")
    tokens = turn.total_tokens
    conversation = _get_turn_conversation(turn)
    tool_count = sum(len(m.tool_calls) for m in turn.messages)
    agent_results = [m for m in turn.messages if m.role == "agent_result" and m.subagent]
    agent_count = sum(
        1 for m in turn.messages for tc in m.tool_calls if tc.tool_name == "Agent"
    )
    turn_cost = turn.estimated_cost
    api_calls = turn.api_call_count
    turn_dur = turn.duration_seconds

    border_color = "#9c27b0" if turn_type == "agent" else "var(--q-primary)"
    with ui.card().classes("w-full").style(
        f"border-left: 3px solid {border_color}; padding: 12px 16px;"
    ):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label(f"Turn {turn.number}").classes("text-xs font-bold")
            ui.badge(turn_type, color=color).classes("text-xs")
            if tokens > 0:
                ui.label(f"{tokens:,} tok").classes("text-xs text-grey-6")
            if turn_cost > 0:
                ui.label(f"~{_format_cost(turn_cost)}").classes("text-xs").style(
                    "color: #00ff41; font-family: monospace;"
                )
            if api_calls > 0:
                ui.badge(
                    f"{api_calls} API call{'s' if api_calls != 1 else ''}",
                    color="grey",
                ).classes("text-xs")
            if agent_count > 0:
                ui.badge(
                    f"{agent_count} agent{'s' if agent_count != 1 else ''}",
                    color="purple",
                ).classes("text-xs")
            elif tool_count > 0:
                ui.badge(
                    f"{tool_count} tool{'s' if tool_count != 1 else ''}",
                    color="orange",
                ).classes("text-xs")
            if turn_dur > 0:
                ui.badge(
                    format_duration(turn_dur), color="blue-grey",
                ).classes("text-xs")

        # conversation recap
        if conversation:
            with ui.column().classes("w-full gap-2 mt-2"):
                for role, content in conversation:
                    if role == "user":
                        with ui.row().classes("items-start gap-2"):
                            ui.icon("person").classes("text-primary text-sm mt-1")
                            with ui.element("div").classes("flex-grow").style(
                                "background: rgba(33, 150, 243, 0.08); "
                                "border-radius: 8px; padding: 8px 12px;"
                            ):
                                ui.html(
                                    f'<pre style="white-space: pre-wrap; '
                                    f"word-break: break-word; margin: 0; "
                                    f'font-size: 0.8rem; max-height: 150px; '
                                    f'overflow-y: auto;">'
                                    f"{_escape_html(content)}</pre>"
                                )
                    else:
                        with ui.row().classes("items-start gap-2"):
                            ui.icon("smart_toy").classes("text-green text-sm mt-1")
                            with ui.element("div").classes("flex-grow").style(
                                "background: rgba(76, 175, 80, 0.08); "
                                "border-radius: 8px; padding: 8px 12px;"
                            ):
                                ui.html(
                                    f'<pre style="white-space: pre-wrap; '
                                    f"word-break: break-word; margin: 0; "
                                    f'font-size: 0.8rem; max-height: 150px; '
                                    f'overflow-y: auto;">'
                                    f"{_escape_html(content)}</pre>"
                                )

        # agent result cards
        if agent_results:
            with ui.column().classes("w-full gap-2 mt-2"):
                for msg in agent_results:
                    _render_agent_result_card(msg.subagent)

        # expandable full details
        is_open = turn.number in expanded_turns
        exp = ui.expansion("Full details", value=is_open).classes("w-full mt-2").props(
            "dense header-class=text-grey-6"
        )

        def _on_toggle(e, tn=turn.number):
            if e.value:
                expanded_turns.add(tn)
            else:
                expanded_turns.discard(tn)

        exp.on_value_change(_on_toggle)

        with exp:
            if tokens > 0:
                _render_turn_token_breakdown(turn)
            for msg in turn.messages:
                _render_message(msg)


def _render_turn_token_breakdown(turn: Turn):
    tb = turn.token_breakdown
    total = tb["input_tokens"] + tb["output_tokens"]
    if total == 0:
        return

    cache_read = tb["cache_read_input_tokens"]
    cache_create = tb["cache_creation_input_tokens"]
    all_input = tb["input_tokens"] + cache_read + cache_create
    cache_ratio = cache_read / all_input if all_input > 0 else 0.0
    turn_cost = turn.estimated_cost
    cbt = turn.cost_by_type

    with ui.element("div").classes("w-full mb-2").style(
        "background: #0d0d1a; border: 1px solid #1a1a2a; "
        "border-radius: 4px; padding: 8px 12px;"
    ):
        with ui.grid(columns=9).classes("gap-1"):
            ui.label("Input:").classes("text-xs text-grey-7")
            ui.label(f"{tb['input_tokens']:,}").classes("text-xs text-grey-5")
            _cost_label(cbt["input"])
            ui.label("Output:").classes("text-xs text-grey-7")
            ui.label(f"{tb['output_tokens']:,}").classes("text-xs text-grey-5")
            _cost_label(cbt["output"])
            ui.label("Total:").classes("text-xs text-grey-7")
            ui.label(f"{total:,}").classes("text-xs text-grey-5")
            _cost_label(turn_cost)
            ui.label("Cache Read:").classes("text-xs text-grey-7")
            ui.label(f"{cache_read:,}").classes("text-xs text-grey-5")
            _cost_label(cbt["cache_read"])
            ui.label("Cache Create:").classes("text-xs text-grey-7")
            ui.label(f"{cache_create:,}").classes("text-xs text-grey-5")
            _cost_label(cbt["cache_create"])
            ui.label("Cache Hit:").classes("text-xs text-grey-7")
            ui.label(f"{cache_ratio:.1%}").classes("text-xs text-grey-5")
            ui.label("").classes("text-xs")


def _render_message(msg: Message):
    if msg.role == "agent_result" and msg.subagent:
        _render_agent_result_card(msg.subagent)
        return

    icon_map = {
        "system": ("settings", "text-blue"),
        "user": ("person", "text-primary"),
        "assistant": ("smart_toy", "text-green"),
        "tool_result": ("output", "text-orange"),
    }
    icon_name, icon_color = icon_map.get(msg.role, ("help", "text-grey-6"))

    with ui.row().classes("items-start gap-2 py-1"):
        ui.icon(icon_name).classes(f"{icon_color} text-xs mt-1")
        with ui.column().classes("gap-1 w-full"):
            role_label = msg.role
            if msg.model:
                role_label += f" ({msg.model})"
            if msg.usage:
                ti = msg.usage.get("input_tokens", 0)
                to = msg.usage.get("output_tokens", 0)
                if ti + to > 0:
                    role_label += f" [{ti + to:,} tok]"
            ui.label(role_label).classes("text-xs font-bold")

            if msg.content:
                _render_text_block(msg.content)

            for tc in msg.tool_calls:
                if tc.tool_name == "Agent":
                    _render_agent_tool_call(tc)
                else:
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("build").classes("text-orange text-xs")
                        ui.label(f"tool_call: {tc.tool_name}").classes(
                            "text-xs font-bold text-orange"
                        )
                    _render_text_block(str(tc.tool_input), color="text-grey-6")

            if msg.subagent and msg.subagent.status == "launched":
                with ui.row().classes("items-center gap-1 mt-1"):
                    ui.icon("rocket_launch").classes("text-purple text-xs")
                    label = msg.subagent.description or msg.subagent.agent_id
                    ui.label(f"launched: {label}").classes(
                        "text-xs font-bold text-purple"
                    )
                    if msg.subagent.model:
                        ui.badge(msg.subagent.model, color="grey").classes("text-xs")

            for tr in msg.tool_results:
                label_cls = (
                    "text-xs font-bold text-red"
                    if tr.is_error
                    else "text-xs font-bold text-orange"
                )
                with ui.row().classes("items-center gap-1"):
                    icon = "error" if tr.is_error else "output"
                    ui.icon(icon).classes("text-orange text-xs")
                    ui.label(f"result: {tr.tool_name}").classes(label_cls)
                if tr.output:
                    _render_text_block(tr.output, color="text-grey-6")


def _render_agent_result_card(info: SubAgentInfo):
    status_color = "green" if info.status == "completed" else "red"
    with ui.card().classes("w-full").style(
        "background: rgba(156, 39, 176, 0.08); "
        "border-left: 3px solid #9c27b0; "
        "padding: 12px 16px;"
    ):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.icon("groups").classes("text-purple text-sm")
            name = info.name or info.description or info.agent_id
            ui.label(name).classes("text-sm font-bold")
            ui.badge(info.status, color=status_color).classes("text-xs")
            if info.model:
                ui.badge(info.model, color="grey").classes("text-xs")

        with ui.row().classes("items-center gap-4 mt-1"):
            if info.duration_ms:
                secs = info.duration_ms / 1000
                with ui.row().classes("items-center gap-1"):
                    ui.icon("schedule").classes("text-xs text-grey-6")
                    ui.label(f"{secs:.1f}s").classes("text-xs text-grey-6")
            if info.subagent_tokens:
                with ui.row().classes("items-center gap-1"):
                    ui.icon("analytics").classes("text-xs text-grey-6")
                    ui.label(f"{info.subagent_tokens:,} tok").classes(
                        "text-xs text-grey-6"
                    )
            if info.tool_uses:
                with ui.row().classes("items-center gap-1"):
                    ui.icon("build").classes("text-xs text-grey-6")
                    ui.label(
                        f"{info.tool_uses} tool{'s' if info.tool_uses != 1 else ''}"
                    ).classes("text-xs text-grey-6")

        if info.result:
            with ui.expansion("Result").classes("w-full mt-1").props(
                "dense header-class=text-grey-6"
            ):
                _render_text_block(info.result)

        if info.session and info.session.turns:
            turn_count = len(info.session.turns)
            label = f"Conversation ({turn_count} turn{'s' if turn_count != 1 else ''})"
            with ui.expansion(label).classes("w-full mt-1").props(
                "dense header-class=text-grey-6"
            ):
                _render_subagent_conversation(info.session)


def _render_subagent_conversation(session):
    """Render a subagent's conversation as a compact turn list."""
    for turn in session.turns:
        conversation = _get_turn_conversation(turn)
        tool_calls = [
            tc for m in turn.messages for tc in m.tool_calls
        ]

        with ui.row().classes("items-start gap-2 py-1 w-full").style(
            "border-left: 2px solid #9c27b044; padding-left: 8px;"
        ):
            with ui.column().classes("gap-1 w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"Turn {turn.number}").classes(
                        "text-xs font-bold text-grey-6"
                    )
                    if turn.total_tokens > 0:
                        ui.label(f"{turn.total_tokens:,} tok").classes(
                            "text-xs text-grey-8"
                        )
                    if tool_calls:
                        names = ", ".join(tc.tool_name for tc in tool_calls[:5])
                        if len(tool_calls) > 5:
                            names += f" +{len(tool_calls) - 5}"
                        ui.label(names).classes("text-xs text-orange")

                for role, content in conversation:
                    if role == "user":
                        with ui.row().classes("items-start gap-1"):
                            ui.icon("person").classes(
                                "text-primary text-xs mt-1"
                            )
                            _render_text_block(content)
                    else:
                        with ui.row().classes("items-start gap-1"):
                            ui.icon("smart_toy").classes(
                                "text-green text-xs mt-1"
                            )
                            _render_text_block(content)


def _render_agent_tool_call(tc):
    name = tc.tool_input.get("name", tc.tool_input.get("description", "Agent"))
    subagent_type = tc.tool_input.get("subagent_type", "")
    prompt = tc.tool_input.get("prompt", "")

    with ui.row().classes("items-center gap-1"):
        ui.icon("groups").classes("text-purple text-xs")
        ui.label(f"Agent: {name}").classes("text-xs font-bold text-purple")
        if subagent_type:
            ui.badge(subagent_type, color="deep-purple-3").classes("text-xs")

    if prompt:
        with ui.expansion("Prompt").classes("w-full").props(
            "dense header-class=text-grey-6"
        ):
            _render_text_block(prompt)


def _render_text_block(text: str, color: str = "text-grey-6"):
    escaped = _escape_html(text)
    ui.html(
        f'<pre style="white-space: pre-wrap; word-break: break-word; '
        f"margin: 2px 0; font-size: 0.75rem; max-height: 300px; "
        f'overflow-y: auto;">{escaped}</pre>'
    ).classes(color)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
