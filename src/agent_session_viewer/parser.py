"""Parse Claude Code JSONL session files into a structured conversation."""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_session_viewer.pricing import estimate_usage_cost


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
class SubAgentInfo:
    agent_id: str = ""
    name: str = ""
    description: str = ""
    model: str = ""
    status: str = ""
    summary: str = ""
    result: str = ""
    duration_ms: int = 0
    subagent_tokens: int = 0
    tool_uses: int = 0
    tool_use_id: str = ""
    agent_type: str = ""
    session: "Session | None" = None


@dataclass
class Message:
    role: str
    content: str = ""
    model: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    timestamp: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    subagent: SubAgentInfo | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Turn:
    number: int
    messages: list[Message] = field(default_factory=list)

    @property
    def turn_type(self) -> str:
        roles = {m.role for m in self.messages}
        has_agent = "agent_result" in roles or any(
            tc.tool_name == "Agent"
            for m in self.messages
            for tc in m.tool_calls
        )
        if has_agent:
            return "agent"
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
                parts = []
                for tc in m.tool_calls:
                    if tc.tool_name == "Agent":
                        name = tc.tool_input.get(
                            "name", tc.tool_input.get("description", "Agent")
                        )
                        parts.append(f"Agent: {name}")
                    else:
                        parts.append(tc.tool_name)
                return ", ".join(parts)
        return ""

    @property
    def duration_seconds(self) -> float:
        """Wall time the model was working, excluding idle gaps > 10 minutes."""
        timestamps: list[datetime] = []
        for m in self.messages:
            ts_str = (
                m.raw.get("timestamp")
                or m.raw.get("payload", {}).get("timestamp", "")
            )
            if not ts_str:
                continue
            try:
                timestamps.append(
                    datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                )
            except (ValueError, TypeError):
                continue
        if len(timestamps) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
            if gap <= 600:
                total += gap
        return total

    @property
    def total_tokens(self) -> int:
        total = 0
        for m in self.messages:
            total += m.usage.get("input_tokens", 0)
            total += m.usage.get("output_tokens", 0)
            total += m.usage.get("reasoning_tokens", 0)
        return total

    @property
    def token_breakdown(self) -> dict[str, int]:
        totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        for m in self.messages:
            for key in totals:
                totals[key] += m.usage.get(key, 0)
        return totals

    @property
    def api_call_count(self) -> int:
        ids = set()
        for m in self.messages:
            if m.role != "assistant":
                continue
            rid = m.raw.get("requestId")
            if rid:
                ids.add(rid)
            else:
                pid = m.raw.get("payload", {}).get("id", "")
                if pid:
                    ids.add(pid)
        return len(ids)

    @property
    def cost_by_type(self) -> dict[str, float]:
        totals = {
            "input": 0.0,
            "output": 0.0,
            "reasoning": 0.0,
            "cache_read": 0.0,
            "cache_create": 0.0,
        }
        for m in self.messages:
            if not m.model or not m.usage:
                continue
            message_cost = estimate_usage_cost(m.model, m.usage)
            for key in totals:
                totals[key] += message_cost[key]
        return totals

    @property
    def estimated_cost(self) -> float:
        return sum(self.cost_by_type.values())


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
            "reasoning_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        for turn in self.turns:
            for msg in turn.messages:
                for key in totals:
                    totals[key] += msg.usage.get(key, 0)
        return totals

    @property
    def total_duration_seconds(self) -> float:
        return sum(turn.duration_seconds for turn in self.turns)

    @property
    def total_subagent_tokens(self) -> int:
        total = 0
        for turn in self.turns:
            for msg in turn.messages:
                if msg.subagent:
                    total += msg.subagent.subagent_tokens
        return total

    @property
    def estimated_cost(self) -> float:
        return sum(turn.estimated_cost for turn in self.turns)

    @property
    def cost_by_type(self) -> dict[str, float]:
        totals = {
            "input": 0.0,
            "output": 0.0,
            "reasoning": 0.0,
            "cache_read": 0.0,
            "cache_create": 0.0,
        }
        for turn in self.turns:
            turn_cbt = turn.cost_by_type
            for key in totals:
                totals[key] += turn_cbt[key]
        return totals

    @property
    def api_call_count(self) -> int:
        return sum(turn.api_call_count for turn in self.turns)

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

    _correlate_agent_names(session)
    _attach_subagent_sessions(session, path)
    return session


def _correlate_agent_names(session: Session):
    """Match agent names from Agent tool calls to their launch/result messages."""
    agent_meta: dict[str, dict[str, str]] = {}
    for turn in session.turns:
        for msg in turn.messages:
            for tc in msg.tool_calls:
                if tc.tool_name == "Agent" and tc.tool_id:
                    agent_meta[tc.tool_id] = {
                        "name": tc.tool_input.get("name", ""),
                        "description": tc.tool_input.get("description", ""),
                    }
            if msg.subagent and msg.subagent.tool_use_id:
                meta = agent_meta.get(msg.subagent.tool_use_id, {})
                if not msg.subagent.name:
                    msg.subagent.name = meta.get("name", "")
                if not msg.subagent.description:
                    msg.subagent.description = meta.get("description", "")


def _attach_subagent_sessions(session: Session, parent_path: Path):
    """Parse subagent JSONL files and attach them to their SubAgentInfo messages."""
    subagent_dir = parent_path.parent / parent_path.stem / "subagents"
    if not subagent_dir.is_dir():
        return

    agents_by_id: dict[str, SubAgentInfo] = {}
    for turn in session.turns:
        for msg in turn.messages:
            if msg.subagent and msg.subagent.agent_id:
                agents_by_id[msg.subagent.agent_id] = msg.subagent

    for meta_path in subagent_dir.glob("agent-*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        agent_id = meta_path.stem.removeprefix("agent-").removesuffix(".meta")
        jsonl_path = meta_path.with_suffix("").with_suffix(".jsonl")
        if not jsonl_path.exists():
            continue

        info = agents_by_id.get(agent_id)
        if info is None:
            continue

        if not info.name:
            info.name = meta.get("name", "")
        if not info.description:
            info.description = meta.get("description", "")
        info.agent_type = meta.get("agentType", "")

        try:
            info.session = _parse_subagent_session(jsonl_path)
        except Exception:
            continue


def _parse_subagent_session(path: Path) -> Session:
    """Parse a subagent JSONL — same format, no recursive subagent attachment."""
    session = Session(session_id=path.stem)
    lines = _read_jsonl(path)

    current_turn_messages: list[Message] = []
    turn_number = 0

    for line in lines:
        msg = _parse_line(line)
        if msg is None:
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
        if isinstance(content, str) and "<task-notification>" in content:
            return None
        if isinstance(content, str) and content.strip():
            return Message(role="user", content=content, raw=line)
        return None

    if line_type == "user":
        msg_data = line.get("message", {})
        msg_content = msg_data.get("content", "")

        origin = line.get("origin", {})
        is_notification = origin.get("kind") == "task-notification" or (
            isinstance(msg_content, str) and "<task-notification>" in msg_content
        )
        if is_notification:
            content_str = msg_content if isinstance(msg_content, str) else ""
            info = _parse_task_notification(content_str)
            if info:
                return Message(role="agent_result", subagent=info, raw=line)
            return None

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

            subagent = None
            tool_use_result = line.get("toolUseResult")
            if isinstance(tool_use_result, dict) and tool_use_result.get("isAsync"):
                first_tool_use_id = ""
                for block in msg_content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        first_tool_use_id = block.get("tool_use_id", "")
                        break
                subagent = SubAgentInfo(
                    agent_id=tool_use_result.get("agentId", ""),
                    description=tool_use_result.get("description", ""),
                    model=tool_use_result.get("resolvedModel", ""),
                    status="launched",
                    tool_use_id=first_tool_use_id,
                )

            return Message(
                role="tool_result", tool_results=tool_results,
                subagent=subagent, raw=line,
            )
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


def _parse_task_notification(content: str) -> SubAgentInfo | None:
    """Parse a <task-notification> XML block into SubAgentInfo."""
    start = content.find("<task-notification>")
    end = content.find("</task-notification>")
    if start == -1 or end == -1:
        return None
    try:
        xml_str = content[start : end + len("</task-notification>")]
        root = ET.fromstring(xml_str)
        usage = root.find("usage")
        return SubAgentInfo(
            agent_id=root.findtext("task-id", ""),
            tool_use_id=root.findtext("tool-use-id", ""),
            status=root.findtext("status", ""),
            summary=root.findtext("summary", ""),
            result=root.findtext("result", ""),
            duration_ms=int(usage.findtext("duration_ms", "0") or "0")
            if usage is not None
            else 0,
            subagent_tokens=int(usage.findtext("subagent_tokens", "0") or "0")
            if usage is not None
            else 0,
            tool_uses=int(usage.findtext("tool_uses", "0") or "0")
            if usage is not None
            else 0,
        )
    except Exception:
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
