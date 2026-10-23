"""Pi coding-agent session provider."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_session_viewer.config import SessionPath, normalize_session_path
from agent_session_viewer.discovery import (
    ProjectInfo,
    SessionInfo,
    file_content_hash,
)
from agent_session_viewer.parser import (
    Message,
    Session,
    ToolCall,
    ToolResult,
    Turn,
)
from agent_session_viewer.pricing import (
    ModelPricing,
    get_pricing as get_claude_pricing,
)
from agent_session_viewer.providers import ProviderBase
from agent_session_viewer.providers.codex import get_codex_pricing

DEFAULT_SESSIONS_PATH = Path.home() / ".pi" / "agent" / "sessions"


class PiProvider(ProviderBase):
    @property
    def slug(self) -> str:
        return "pi"

    @property
    def name(self) -> str:
        return "Pi"

    def default_paths(self) -> list[Path]:
        return [DEFAULT_SESSIONS_PATH]

    def discover_projects(
        self, paths: list[Path | SessionPath],
    ) -> list[ProjectInfo]:
        projects_by_name: dict[str, ProjectInfo] = {}
        seen_paths: set[Path] = set()

        for path_entry in paths:
            spec = normalize_session_path(path_entry)
            seen_hashes: set[str] = set()
            for session_path in _session_files(spec):
                if (
                    not session_path.is_file()
                    or session_path.suffix.lower() != ".jsonl"
                ):
                    continue
                resolved = session_path.resolve()
                if resolved in seen_paths:
                    continue
                if spec.deduplicate:
                    digest = file_content_hash(session_path)
                    if digest is not None:
                        if digest in seen_hashes:
                            continue
                        seen_hashes.add(digest)

                session = _parse_pi_session(session_path)
                if not session.session_id:
                    continue
                try:
                    stat = session_path.stat()
                except OSError:
                    continue

                cwd = str(session.metadata.get("cwd", "") or "")
                project_name = _project_name(cwd, session_path.parent.name)
                project_path = Path(cwd) if cwd else session_path.parent
                project = projects_by_name.get(project_name)
                if project is None:
                    project = ProjectInfo(
                        name=project_name,
                        path=project_path,
                        provider=self.slug,
                    )
                    projects_by_name[project_name] = project

                project.sessions.append(SessionInfo(
                    session_id=session.session_id,
                    path=session_path,
                    size_bytes=stat.st_size,
                    mtime=stat.st_mtime,
                    provider=self.slug,
                    cwd=cwd,
                    title=str(session.metadata.get("title", "") or ""),
                    turn_count=session.total_turns,
                    api_call_count=session.api_call_count,
                ))
                seen_paths.add(resolved)

        for project in projects_by_name.values():
            project.sessions.sort(key=lambda item: item.mtime, reverse=True)

        projects = list(projects_by_name.values())
        projects.sort(
            key=lambda project: max(
                (session.mtime for session in project.sessions), default=0,
            ),
            reverse=True,
        )
        return projects

    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        session = _parse_pi_session(path)
        if session.session_id:
            return session
        return Session(session_id=session_id or _filename_session_id(path))

    def extract_tail_exchanges(
        self,
        path: Path,
        max_exchanges: int = 3,
        session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        if max_exchanges <= 0:
            return []
        session = _parse_pi_session(path)
        exchanges: list[tuple[str, str]] = []
        for turn in session.turns:
            user_text = next(
                (message.content for message in turn.messages
                 if message.role == "user" and message.content),
                "",
            )
            assistant_text = "\n".join(
                message.content
                for message in turn.messages
                if message.role == "assistant"
                and message.content
                and not message.content.startswith("[thinking] ")
            )
            if user_text or assistant_text:
                exchanges.append((user_text, assistant_text))
        return exchanges[-max_exchanges:]

    def get_pricing(self, model: str) -> ModelPricing | None:
        provider, separator, model_id = model.partition("/")
        if not separator:
            return get_claude_pricing(model)
        if provider in {"anthropic", "claude"}:
            return get_claude_pricing(model_id)
        if provider in {"openai", "openai-codex"}:
            return get_codex_pricing(model_id)
        return None


def _session_files(spec: SessionPath) -> Iterator[Path]:
    path = spec.path
    try:
        if path.is_file():
            if path.suffix.lower() == ".jsonl":
                yield path
            return
        if not path.is_dir():
            return

        if spec.recursive is True:
            yield from sorted(path.rglob("*.jsonl"))
        elif spec.recursive is False:
            yield from sorted(path.glob("*.jsonl"))
        else:
            # Pi's default layout is sessions/<encoded-project>/*.jsonl. Also
            # accept a configured project directory containing files directly.
            candidates = set(path.glob("*.jsonl"))
            for project_dir in path.iterdir():
                if project_dir.is_dir():
                    candidates.update(project_dir.glob("*.jsonl"))
            yield from sorted(candidates)
    except OSError:
        return


def _read_session_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as session_file:
            for line in session_file:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return {}, []

    if not entries or entries[0].get("type") != "session":
        return {}, []
    header = entries[0]
    if not isinstance(header.get("id"), str) or not header["id"]:
        return {}, []
    return header, entries[1:]


def _active_branch(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the tree path to Pi's current leaf (the last persisted entry)."""
    if not entries:
        return []

    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            by_id[entry_id] = entry

    leaf_id = entries[-1].get("id")
    if not isinstance(leaf_id, str) or not leaf_id or not by_id:
        # Version 1 sessions predate parent links and are linear.
        return entries

    branch: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = by_id.get(leaf_id)
    while current is not None:
        current_id = current.get("id")
        if not isinstance(current_id, str) or current_id in seen:
            break
        seen.add(current_id)
        branch.append(current)
        parent_id = current.get("parentId")
        current = by_id.get(parent_id) if isinstance(parent_id, str) else None
    branch.reverse()
    return branch


def _parse_pi_session(path: Path) -> Session:
    header, entries = _read_session_file(path)
    if not header:
        return Session(session_id="")

    session = Session(session_id=header["id"])
    cwd = header.get("cwd", "")
    session.metadata.update({
        "cwd": cwd if isinstance(cwd, str) else "",
        "version": header.get("version", 1),
        "created_at": header.get("timestamp", ""),
        "parent_session": header.get("parentSession", ""),
    })

    current_messages: list[Message] = []
    current_turn_has_user = False
    turn_number = 0
    current_model = ""

    def finish_turn() -> None:
        nonlocal current_messages, current_turn_has_user, turn_number
        if current_messages:
            turn_number += 1
            session.turns.append(Turn(
                number=turn_number,
                messages=current_messages,
            ))
        current_messages = []
        current_turn_has_user = False

    for entry in _active_branch(entries):
        entry_type = entry.get("type", "")
        if entry_type == "session_info":
            name = entry.get("name")
            if isinstance(name, str):
                session.metadata["title"] = name.strip()
            continue
        if entry_type == "model_change":
            current_model = _model_name(
                entry.get("provider", ""), entry.get("modelId", ""),
            )
            if current_model:
                session.model = current_model
            continue

        messages = _messages_from_entry(entry, current_model)
        for message in messages:
            if message.role == "user" and message.content.strip():
                if current_turn_has_user:
                    finish_turn()
                current_turn_has_user = True
            if message.role == "assistant" and message.model:
                current_model = message.model
                session.model = message.model
            current_messages.append(message)

    finish_turn()
    return session


def _messages_from_entry(
    entry: dict[str, Any], current_model: str,
) -> list[Message]:
    entry_type = entry.get("type", "")
    raw = {
        "timestamp": entry.get("timestamp", ""),
        "id": entry.get("id", ""),
    }

    if entry_type == "message":
        message = entry.get("message")
        if not isinstance(message, dict):
            return []
        role = message.get("role", "")
        timestamp = _message_timestamp(message.get("timestamp"))
        raw = dict(raw, timestamp=entry.get("timestamp", ""))

        if role == "system":
            text = _content_text(message.get("content", ""))
            return [Message(
                role="system", content=text, timestamp=timestamp, raw=raw,
            )] if text else []

        if role == "user":
            text = _content_text(message.get("content", ""), include_images=True)
            return [Message(
                role="user", content=text, timestamp=timestamp, raw=raw,
            )] if text else []

        if role == "assistant":
            provider = message.get("provider", "")
            model = _model_name(provider, message.get("model", "")) or current_model
            usage = _usage(message.get("usage"))
            request_id = entry.get("id") or message.get("responseId")
            assistant_raw = dict(raw)
            if request_id:
                assistant_raw["requestId"] = request_id
            output: list[Message] = []
            content = message.get("content", [])
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if not isinstance(content, list):
                content = []

            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    text = block.get("text", "")
                    if isinstance(text, str) and text:
                        output.append(Message(
                            role="assistant", content=text, model=model,
                            timestamp=timestamp, raw=dict(assistant_raw),
                        ))
                elif block_type == "thinking":
                    thinking = block.get("thinking", "")
                    if isinstance(thinking, str) and thinking:
                        output.append(Message(
                            role="assistant", content=f"[thinking] {thinking}",
                            model=model, timestamp=timestamp,
                            raw=dict(assistant_raw),
                        ))
                elif block_type == "toolCall":
                    arguments = block.get("arguments", {})
                    output.append(Message(
                        role="assistant",
                        model=model,
                        tool_calls=[ToolCall(
                            tool_name=str(block.get("name", "tool")),
                            tool_input=(
                                arguments if isinstance(arguments, dict)
                                else {"raw": str(arguments)}
                            ),
                            tool_id=str(block.get("id", "")),
                        )],
                        timestamp=timestamp,
                        raw=dict(assistant_raw),
                    ))

            if not output:
                output.append(Message(
                    role="assistant", model=model, timestamp=timestamp,
                    raw=assistant_raw,
                ))
            if usage:
                output[0].usage = usage
            return output

        if role == "toolResult":
            content = _content_text(message.get("content", ""), include_images=True)
            return [Message(
                role="tool_result",
                tool_results=[ToolResult(
                    tool_name=str(message.get("toolName", "")),
                    output=content,
                    tool_id=str(message.get("toolCallId", "")),
                    is_error=bool(message.get("isError", False)),
                )],
                timestamp=timestamp,
                raw=raw,
            )]

        if role == "bashExecution":
            command = str(message.get("command", ""))
            output_text = str(message.get("output", ""))
            tool_id = str(entry.get("id", ""))
            return [Message(
                role="assistant",
                tool_calls=[ToolCall(
                    tool_name="bash",
                    tool_input={"command": command},
                    tool_id=tool_id,
                )],
                timestamp=timestamp,
                raw=raw,
            ), Message(
                role="tool_result",
                tool_results=[ToolResult(
                    tool_name="bash",
                    output=output_text,
                    tool_id=tool_id,
                    is_error=(
                        (
                            message.get("exitCode") is not None
                            and _safe_int(message.get("exitCode")) != 0
                        )
                        or bool(message.get("cancelled", False))
                    ),
                )],
                timestamp=timestamp,
                raw=raw,
            )]

        if role == "custom":
            text = _content_text(message.get("content", ""), include_images=True)
            if text and message.get("display", True):
                return [Message(
                    role="user", content=text, timestamp=timestamp, raw=raw,
                )]
        elif role == "branchSummary":
            summary = message.get("summary", "")
            if isinstance(summary, str) and summary:
                return [Message(
                    role="assistant", content=f"[branch summary] {summary}",
                    model=current_model, timestamp=timestamp, raw=raw,
                )]
        elif role == "compactionSummary":
            summary = message.get("summary", "")
            if isinstance(summary, str) and summary:
                return [Message(
                    role="assistant", content=f"[compaction] {summary}",
                    model=current_model, timestamp=timestamp, raw=raw,
                )]
        return []

    if entry_type in {"compaction", "branch_summary"}:
        summary = entry.get("summary", "")
        if not isinstance(summary, str) or not summary:
            return []
        model = current_model
        usage = _usage(entry.get("usage"))
        message = Message(
            role="assistant",
            content=("[compaction] " if entry_type == "compaction" else "[branch summary] ") + summary,
            model=model,
            timestamp=_message_timestamp(entry.get("timestamp")),
            raw=raw,
        )
        if usage:
            message.usage = usage
        return [message]

    if entry_type == "custom_message" and entry.get("display", False):
        text = _content_text(entry.get("content", ""), include_images=True)
        if text:
            custom_type = entry.get("customType", "extension")
            return [Message(
                role="user",
                content=f"[custom: {custom_type}] {text}",
                timestamp=_message_timestamp(entry.get("timestamp")),
                raw=raw,
            )]

    if entry_type == "usage":
        usage = _usage(entry.get("usage"))
        if not usage:
            return []
        model = _model_name(entry.get("provider", ""), entry.get("model", ""))
        return [Message(
            role="system",
            content="",
            model=model or current_model,
            usage=usage,
            timestamp=_message_timestamp(entry.get("timestamp")),
            raw=raw,
        )]

    return []


def _content_text(content: Any, include_images: bool = False) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
            elif include_images and block.get("type") == "image":
                mime_type = block.get("mimeType", "image")
                parts.append(f"[image: {mime_type}]")
    return "\n".join(part for part in parts if part)


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    if not any(
        key in value
        for key in ("input", "output", "reasoning", "cacheRead", "cacheWrite")
    ):
        return {}
    reasoning = _safe_int(value.get("reasoning", 0))
    output = _safe_int(value.get("output", 0))
    return {
        "input_tokens": _safe_int(value.get("input", 0)),
        "output_tokens": max(0, output - reasoning),
        "reasoning_tokens": reasoning,
        "cache_read_input_tokens": _safe_int(value.get("cacheRead", 0)),
        "cache_creation_input_tokens": _safe_int(value.get("cacheWrite", 0)),
    }


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _message_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                value / 1000, tz=timezone.utc,
            ).isoformat()
        except (OSError, OverflowError, ValueError):
            return ""
    return value if isinstance(value, str) else ""


def _model_name(provider: Any, model: Any) -> str:
    if not isinstance(model, str) or not model:
        return ""
    if isinstance(provider, str) and provider:
        return f"{provider}/{model}"
    return model


def _project_name(cwd: str, fallback: str) -> str:
    if cwd:
        name = re.sub(r"[^a-zA-Z0-9]", "-", cwd).strip("-")
        if name:
            return name
    return fallback.strip("-") or "unknown"


def _filename_session_id(path: Path) -> str:
    # Pi filenames use <timestamp>_<session-id>.jsonl; the header is canonical.
    return path.stem.rsplit("_", 1)[-1]
