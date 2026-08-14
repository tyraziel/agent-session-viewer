"""Parse Claude Code JSONL session files into a structured conversation."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolCall:
    tool_name: str
    tool_input: dict[str, Any]
    tool_id: str = ""


@dataclass
class ToolResult:
    tool_name: str
    output: str
    tool_id: str = ""
    is_error: bool = False


@dataclass
class Message:
    role: str
    content: str = ""
    model: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    timestamp: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Turn:
    number: int
    messages: list[Message] = field(default_factory=list)

    @property
    def turn_type(self) -> str:
        roles = {m.role for m in self.messages}
        if "system" in roles:
            return "system"
        if "user" in roles:
            has_tool = any(m.tool_calls or m.tool_results for m in self.messages)
            if has_tool:
                return "tool_use"
            return "user"
        if "assistant" in roles:
            has_tool = any(m.tool_calls for m in self.messages)
            if has_tool:
                return "tool_use"
            return "assistant"
        return "unknown"

    @property
    def preview(self) -> str:
        for m in self.messages:
            if m.role == "user" and m.content:
                return _truncate(m.content, 120)
            if m.role == "assistant" and m.content:
                return _truncate(m.content, 120)
            if m.tool_calls:
                names = ", ".join(tc.tool_name for tc in m.tool_calls)
                return f"tool: {names}"
        return ""

    @property
    def total_tokens(self) -> int:
        total = 0
        for m in self.messages:
            total += m.usage.get("input_tokens", 0)
            total += m.usage.get("output_tokens", 0)
        return total


@dataclass
class Session:
    session_id: str
    model: str = ""
    turns: list[Turn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> dict[str, int]:
        totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        for turn in self.turns:
            for msg in turn.messages:
                for key in totals:
                    totals[key] += msg.usage.get(key, 0)
        return totals

    @property
    def total_turns(self) -> int:
        return len(self.turns)


def parse_session(path: Path) -> Session:
    session = Session(session_id=path.stem)
    lines = _read_jsonl(path)

    current_turn_messages: list[Message] = []
    turn_number = 0
    last_role = None

    for line in lines:
        msg = _parse_line(line)
        if msg is None:
            if line.get("type") in ("mode", "permission-mode", "config"):
                session.metadata.update(line)
            continue

        if not session.model and msg.model:
            session.model = msg.model

        if msg.role == "user" and msg.content.strip():
            if current_turn_messages:
                turn_number += 1
                session.turns.append(Turn(
                    number=turn_number,
                    messages=current_turn_messages,
                ))
            current_turn_messages = []

        current_turn_messages.append(msg)
        last_role = msg.role

    if current_turn_messages:
        turn_number += 1
        session.turns.append(Turn(
            number=turn_number,
            messages=current_turn_messages,
        ))

    return session


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                lines.append(json.loads(raw_line))
            except json.JSONDecodeError:
                continue
    return lines


def _parse_line(line: dict[str, Any]) -> Message | None:
    line_type = line.get("type", "")

    if line_type == "queue-operation" and line.get("operation") == "enqueue":
        content = line.get("content", "")
        if isinstance(content, str) and content.strip():
            return Message(role="user", content=content, raw=line)
        return None

    if line_type == "user":
        msg_data = line.get("message", {})
        msg_content = msg_data.get("content", "")
        if isinstance(msg_content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in msg_content
        ):
            tool_results = []
            for block in msg_content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    output_text = _extract_content_text(block.get("content", ""))
                    tool_results.append(ToolResult(
                        tool_name=block.get("name", ""),
                        output=output_text,
                        tool_id=block.get("tool_use_id", ""),
                        is_error=block.get("is_error", False),
                    ))
            return Message(role="tool_result", tool_results=tool_results, raw=line)
        content = _extract_content(msg_data)
        return Message(role="user", content=content, raw=line)

    if line_type == "assistant":
        msg_data = line.get("message", {})
        content = _extract_content(msg_data)
        model = msg_data.get("model", "")
        usage = msg_data.get("usage", {})

        tool_calls = []
        msg_content = msg_data.get("content", [])
        if isinstance(msg_content, list):
            for block in msg_content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(
                        tool_name=block.get("name", ""),
                        tool_input=block.get("input", {}),
                        tool_id=block.get("id", ""),
                    ))

        return Message(
            role="assistant",
            content=content,
            model=model,
            usage=usage,
            tool_calls=tool_calls,
            raw=line,
        )

    if line_type == "tool_result":
        tool_results = []
        msg_content = line.get("message", {}).get("content", [])
        if isinstance(msg_content, list):
            for block in msg_content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    output_text = _extract_content_text(block.get("content", ""))
                    tool_results.append(ToolResult(
                        tool_name=block.get("name", ""),
                        output=output_text,
                        tool_id=block.get("tool_use_id", ""),
                        is_error=block.get("is_error", False),
                    ))

        return Message(
            role="tool_result",
            tool_results=tool_results,
            raw=line,
        )

    if line_type == "system":
        content = _extract_content(line.get("message", {}))
        return Message(role="system", content=content, raw=line)

    return None


def _extract_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _extract_content_text(content)
    return str(content) if content else ""


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    parts.append(_extract_content_text(block.get("content", "")))
        return "\n".join(parts)
    return str(content) if content else ""


def _truncate(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
