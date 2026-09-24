"""OpenAI Codex CLI session provider."""

import json
import re
from dataclasses import field
from pathlib import Path
from typing import Any

from agent_session_viewer.discovery import ProjectInfo, SessionInfo
from agent_session_viewer.parser import (
    Message,
    Session,
    ToolCall,
    ToolResult,
    Turn,
)
from agent_session_viewer.pricing import ModelPricing, ModelRates
from agent_session_viewer.providers import ProviderBase


def _openai_rates(
    input: float,
    output: float,
    cached: float | None = None,
    cache_write: float | None = None,
    long_context: ModelRates | None = None,
) -> ModelPricing:
    """Build Standard API rates; absent cache rates use regular input price."""
    return ModelPricing(
        input=input,
        output=output,
        cache_read=input if cached is None else cached,
        cache_write=input if cache_write is None else cache_write,
        long_context=long_context,
    )


def _long_rates(
    input: float,
    output: float,
    cached: float | None = None,
    cache_write: float | None = None,
) -> ModelRates:
    return ModelRates(
        input=input,
        output=output,
        cache_read=input if cached is None else cached,
        cache_write=input if cache_write is None else cache_write,
    )


# OpenAI Standard API text-token rates per million tokens. When the pricing
# page has no separate cache-write price, cache creation is billed at input
# rates. Long-context rates apply to the whole request above 272K input tokens.
_CODEX_PRICING: dict[str, ModelPricing] = {
    "gpt-6-astra": _openai_rates(
        10.00, 50.00, 1.00, 12.50,
        _long_rates(20.00, 75.00, 2.00, 25.00),
    ),
    "gpt-6-sol": _openai_rates(
        2.00, 10.00, 0.20, 2.50,
        _long_rates(4.00, 15.00, 0.40, 5.00),
    ),
    "gpt-6-luna": _openai_rates(
        0.10, 0.50, 0.01, 0.125,
        _long_rates(0.20, 0.75, 0.02, 0.25),
    ),
    "gpt-5.6-sol": _openai_rates(
        4.00, 20.00, 0.40, 5.00,
        _long_rates(8.00, 30.00, 0.80, 10.00),
    ),
    "gpt-5.6-terra": _openai_rates(
        2.00, 12.00, 0.20, 2.50,
        _long_rates(4.00, 18.00, 0.40, 5.00),
    ),
    "gpt-5.6-luna": _openai_rates(
        0.20, 1.20, 0.02, 0.25,
        _long_rates(0.40, 1.80, 0.04, 0.50),
    ),
    "gpt-5.6-cyber": _openai_rates(12.50, 75.00, 1.25, 15.625),
    "gpt-5.5-cyber": _openai_rates(12.50, 75.00, 1.25),
    "gpt-5.5-pro": _openai_rates(
        30.00, 180.00,
        long_context=_long_rates(60.00, 270.00),
    ),
    "gpt-5.5": _openai_rates(
        5.00, 30.00, 0.50,
        long_context=_long_rates(10.00, 45.00, 1.00),
    ),
    "gpt-5.4-pro": _openai_rates(
        30.00, 180.00,
        long_context=_long_rates(60.00, 270.00),
    ),
    "gpt-5.4-mini": _openai_rates(0.75, 4.50, 0.075),
    "gpt-5.4-nano": _openai_rates(0.20, 1.25, 0.02),
    "gpt-5.4": _openai_rates(
        2.50, 15.00, 0.25,
        long_context=_long_rates(5.00, 22.50, 0.50),
    ),
    "gpt-5.3-codex": _openai_rates(1.75, 14.00, 0.175),
    "gpt-5.2-pro": _openai_rates(21.00, 168.00),
    "gpt-5.2": _openai_rates(1.75, 14.00, 0.175),
    "gpt-5.1": _openai_rates(1.25, 10.00, 0.125),
    "gpt-5-pro": _openai_rates(15.00, 120.00),
    "gpt-5-mini": _openai_rates(0.25, 2.00, 0.025),
    "gpt-5-nano": _openai_rates(0.05, 0.40, 0.005),
    "gpt-5": _openai_rates(1.25, 10.00, 0.125),
    "gpt-4.1-nano": _openai_rates(0.10, 0.40, 0.025),
    "gpt-4.1-mini": _openai_rates(0.40, 1.60, 0.10),
    "gpt-4.1": _openai_rates(2.00, 8.00, 0.50),
    "gpt-4o-2024-05-13": _openai_rates(5.00, 15.00),
    "gpt-4o-mini": _openai_rates(0.15, 0.60, 0.075),
    "gpt-4o": _openai_rates(2.50, 10.00, 1.25),
    "gpt-4-turbo-2024-04-09": _openai_rates(10.00, 30.00),
    "gpt-4-0613": _openai_rates(30.00, 60.00),
    "gpt-3.5-turbo-instruct": _openai_rates(1.50, 2.00),
    "gpt-3.5-turbo-0125": _openai_rates(0.50, 1.50),
    "gpt-3.5-turbo-1106": _openai_rates(1.00, 2.00),
    "gpt-3.5-turbo": _openai_rates(0.50, 1.50),
    "o1-pro": _openai_rates(150.00, 600.00),
    "o3-pro": _openai_rates(20.00, 80.00),
    "o4-mini": _openai_rates(1.10, 4.40, 0.275),
    "o3-mini": _openai_rates(1.10, 4.40, 0.55),
    "o1": _openai_rates(15.00, 60.00, 7.50),
    "o3": _openai_rates(2.00, 8.00, 0.50),
    "chat-latest": _openai_rates(5.00, 30.00, 0.50),
    "gpt-5-search-api": _openai_rates(1.25, 10.00, 0.125),
    "gpt-daybreak-blue-latest": _openai_rates(
        4.00, 20.00, 0.40, 5.00,
        _long_rates(8.00, 30.00, 0.80, 10.00),
    ),
    "gpt-daybreak-red-latest": _openai_rates(12.50, 75.00, 1.25, 15.625),
    "davinci-002": _openai_rates(2.00, 2.00),
    "babbage-002": _openai_rates(0.40, 0.40),
}

_FILENAME_RE = re.compile(
    r"rollout-(\d{4}-\d{2}-\d{2})T(\d{2}-\d{2}-\d{2})-([0-9a-f-]+)\.jsonl$"
)


def _load_session_index() -> dict[str, str]:
    """Load session titles from ~/.codex/session_index.jsonl.

    Returns an empty dict if the file is missing, unreadable, or corrupt.
    Malformed lines are skipped individually.
    """
    index_path = Path.home() / ".codex" / "session_index.jsonl"
    titles: dict[str, str] = {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    sid = obj.get("id", "")
                    name = obj.get("thread_name", "")
                    if sid and name:
                        titles[sid] = name
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass
    return titles


class CodexProvider(ProviderBase):
    @property
    def slug(self) -> str:
        return "codex"

    @property
    def name(self) -> str:
        return "Codex"

    def default_paths(self) -> list[Path]:
        return [Path.home() / ".codex" / "sessions"]

    def discover_projects(self, paths: list[Path]) -> list[ProjectInfo]:
        projects_by_cwd: dict[str, ProjectInfo] = {}
        session_titles = _load_session_index()

        for base_dir in paths:
            if not base_dir.is_dir():
                continue
            for jsonl in base_dir.rglob("rollout-*.jsonl"):
                if not jsonl.is_file():
                    continue
                stat = jsonl.stat()
                session_id, _ = _parse_filename(jsonl.name)
                cwd, meta_title = _extract_codex_meta(jsonl)
                title = session_titles.get(session_id, meta_title)
                turn_count, api_call_count = _count_codex_turns(jsonl)
                slug = _cwd_to_slug(cwd) if cwd else jsonl.parent.name

                session = SessionInfo(
                    session_id=session_id,
                    path=jsonl,
                    size_bytes=stat.st_size,
                    mtime=stat.st_mtime,
                    provider=self.slug,
                    cwd=cwd,
                    title=title,
                    turn_count=turn_count,
                    api_call_count=api_call_count,
                )

                if slug not in projects_by_cwd:
                    projects_by_cwd[slug] = ProjectInfo(
                        name=slug,
                        path=jsonl.parent,
                        provider=self.slug,
                    )
                projects_by_cwd[slug].sessions.append(session)

        for project in projects_by_cwd.values():
            project.sessions.sort(key=lambda s: s.mtime, reverse=True)

        projects = list(projects_by_cwd.values())
        projects.sort(
            key=lambda p: max(s.mtime for s in p.sessions), reverse=True,
        )
        return projects

    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        return _parse_codex_session(path)

    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3, session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        return _extract_codex_tail(path, max_exchanges)

    def get_pricing(self, model: str) -> ModelPricing | None:
        return get_codex_pricing(model)


def get_codex_pricing(model: str) -> ModelPricing | None:
    for prefix in sorted(_CODEX_PRICING, key=len, reverse=True):
        if model.startswith(prefix):
            return _CODEX_PRICING[prefix]
    return None


def _parse_filename(name: str) -> tuple[str, str]:
    """Extract (session_id, date) from rollout filename."""
    m = _FILENAME_RE.search(name)
    if m:
        return m.group(3), m.group(1)
    return name.removesuffix(".jsonl"), ""


def _cwd_to_slug(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd).strip("-")


def _extract_codex_meta(path: Path) -> tuple[str, str]:
    """Read session_meta for cwd and a title."""
    cwd = ""
    title = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "session_meta":
                    p = obj.get("payload", {})
                    cwd = p.get("cwd", "")
                    title = p.get("title", "")
                    break
    except OSError:
        pass
    return cwd, title


def _count_codex_turns(path: Path) -> tuple[int, int]:
    """Count turns (task_started events) and API calls (token_count events)."""
    turns = 0
    api_calls = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '"task_started"' in line:
                    try:
                        obj = json.loads(line)
                        if (obj.get("type") == "event_msg"
                                and obj.get("payload", {}).get("type") == "task_started"):
                            turns += 1
                    except json.JSONDecodeError:
                        continue
                elif '"token_count"' in line:
                    try:
                        obj = json.loads(line)
                        if (obj.get("type") == "event_msg"
                                and obj.get("payload", {}).get("type") == "token_count"):
                            api_calls += 1
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return turns, api_calls


def _extract_text(content: list[dict]) -> str:
    """Extract text from Codex content blocks (input_text or output_text)."""
    for block in content:
        if isinstance(block, dict):
            if block.get("type") in ("input_text", "output_text"):
                text = block.get("text", "").strip()
                if text:
                    return text
    return ""


def _parse_codex_session(path: Path) -> Session:
    """Parse a Codex rollout JSONL into the shared Session model."""
    session = Session(session_id=path.stem)
    lines = _read_jsonl(path)

    current_turn_messages: list[Message] = []
    turn_number = 0
    current_turn_id = None
    current_model = ""

    for obj in lines:
        outer_type = obj.get("type", "")
        payload = obj.get("payload", {})

        if outer_type == "session_meta":
            session.session_id = payload.get("session_id", session.session_id)
            continue

        if outer_type == "turn_context":
            current_model = payload.get("model", "") or current_model
            if not session.model:
                session.model = current_model
            continue

        if outer_type == "event_msg":
            inner = payload.get("type", "")
            if inner == "task_started":
                if current_turn_messages:
                    turn_number += 1
                    session.turns.append(Turn(
                        number=turn_number,
                        messages=current_turn_messages,
                    ))
                current_turn_messages = []
                current_turn_id = payload.get("turn_id", "")
            elif inner == "token_count":
                usage = _codex_token_usage(payload)
                if usage:
                    for message in reversed(current_turn_messages):
                        if message.role == "assistant" and not message.usage:
                            message.model = message.model or current_model
                            message.usage = usage
                            break
            continue

        if outer_type == "response_item":
            msg = _parse_codex_response_item(payload, obj)
            if msg:
                current_turn_messages.append(msg)
            continue

    if current_turn_messages:
        turn_number += 1
        session.turns.append(Turn(
            number=turn_number,
            messages=current_turn_messages,
        ))

    return session


def _codex_token_usage(payload: dict) -> dict[str, int]:
    """Normalize a Codex token_count event's last-call usage."""
    info = payload.get("info", {})
    if not isinstance(info, dict):
        info = {}
    last_usage = info.get("last_token_usage") or payload.get("last_token_usage")
    if not isinstance(last_usage, dict) or not any(
        key in last_usage
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    ):
        return {}

    input_tokens = _safe_int(last_usage.get("input_tokens", 0))
    cached_input_tokens = _safe_int(last_usage.get("cached_input_tokens", 0))
    output_tokens = _safe_int(last_usage.get("output_tokens", 0))
    reasoning_tokens = _safe_int(last_usage.get("reasoning_output_tokens", 0))
    return {
        "input_tokens": max(0, input_tokens - cached_input_tokens),
        # Codex reports reasoning as a detail within the output token count.
        "output_tokens": max(0, output_tokens - reasoning_tokens),
        "reasoning_tokens": reasoning_tokens,
        "cache_read_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": 0,
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_codex_response_item(payload: dict, raw: dict) -> Message | None:
    ptype = payload.get("type", "")
    role = payload.get("role", "")
    content = payload.get("content", [])

    if ptype == "message":
        if role == "user":
            text = _extract_text(content) if isinstance(content, list) else ""
            if text:
                return Message(role="user", content=text, raw=raw)
        elif role == "assistant":
            text = _extract_text(content) if isinstance(content, list) else ""
            if text:
                return Message(role="assistant", content=text, raw=raw)
        elif role == "developer":
            return Message(role="system", content="[developer message]", raw=raw)
        return None

    if ptype == "reasoning":
        summary = payload.get("summary", "")
        if summary:
            return Message(role="assistant", content=f"[thinking] {summary}", raw=raw)
        return None

    if ptype == "custom_tool_call":
        name = payload.get("name", "")
        call_id = payload.get("call_id", "")
        input_data = payload.get("input", "")
        if isinstance(input_data, list):
            input_data = _extract_text(input_data)
        if isinstance(input_data, str):
            input_data = {"command": input_data}
        tc = ToolCall(
            tool_name=name,
            tool_input=input_data if isinstance(input_data, dict) else {"raw": str(input_data)},
            tool_id=call_id,
        )
        return Message(role="assistant", tool_calls=[tc], raw=raw)

    if ptype == "custom_tool_call_output":
        call_id = payload.get("call_id", "")
        output = payload.get("output", "")
        if isinstance(output, list):
            output = _extract_text(output)
        elif not isinstance(output, str):
            output = str(output)
        tr = ToolResult(
            tool_name="",
            output=output,
            tool_id=call_id,
        )
        return Message(role="tool_result", tool_results=[tr], raw=raw)

    return None


def _extract_codex_tail(
    path: Path, max_exchanges: int = 3,
) -> list[tuple[str, str]]:
    """Read the tail of a Codex JSONL for active session cards."""
    user_texts: list[str] = []
    assistant_texts: list[str] = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk_size = min(size, 65536)
            f.seek(size - chunk_size)
            data = f.read().decode("utf-8", errors="replace")

        for raw_line in reversed(data.strip().split("\n")):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "response_item":
                continue
            p = obj.get("payload", {})
            if p.get("type") != "message":
                continue
            role = p.get("role", "")
            content = p.get("content", [])
            text = _extract_text(content) if isinstance(content, list) else ""
            if not text:
                continue

            if role == "assistant":
                assistant_texts.append(text)
            elif role == "user":
                user_texts.append(text)

            if (len(user_texts) >= max_exchanges
                    and len(assistant_texts) >= max_exchanges):
                break
    except OSError:
        pass

    user_texts.reverse()
    assistant_texts.reverse()
    messages: list[tuple[str, str]] = []
    for i in range(min(len(user_texts), len(assistant_texts))):
        messages.append((user_texts[i], assistant_texts[i]))
    if len(user_texts) > len(assistant_texts):
        messages.append((user_texts[-1], ""))
    return messages[-max_exchanges:]


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
