"""OpenCode session provider (SQLite-backed).

OpenCode stores transcripts in a single SQLite database
(`~/.local/share/opencode/opencode.db` by default) rather than one file
per session. The DB contains `session`, `message`, and `part` tables;
`message.data` and `part.data` are JSON blobs.

`SessionInfo.path` is the DB file; `session_id` selects the session
within it. Multiple DBs can be configured via the provider's
`session_paths` (each entry may be a `.db` file or a directory to
scan for `.db` files).
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_session_viewer.discovery import ProjectInfo, SessionInfo
from agent_session_viewer.parser import (
    Message,
    Session,
    ToolCall,
    ToolResult,
    Turn,
)
from agent_session_viewer.pricing import ModelPricing, get_pricing
from agent_session_viewer.providers import ProviderBase

from agent_session_viewer.providers.codex import get_codex_pricing

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

_REQUIRED_TABLES = ("session", "message", "part")

_DISCOVER_SQL = """
select
    s.id,
    s.directory,
    s.title,
    s.time_updated,
    (select coalesce(sum(length(mm.data)), 0)
       from message mm where mm.session_id = s.id)
  + (select coalesce(sum(length(pp.data)), 0)
       from part pp where pp.session_id = s.id) as byte_count,
    (select count(distinct pp2.message_id)
       from part pp2
      where pp2.session_id = s.id
        and json_extract(pp2.data, '$.type') = 'text'
        and json_extract(pp2.data, '$.text') is not null
        and exists (
            select 1 from message mm2
             where mm2.id = pp2.message_id
               and json_extract(mm2.data, '$.role') = 'user'
        )
    ) as turn_count,
    (select count(*)
       from message mm3
      where mm3.session_id = s.id
        and json_extract(mm3.data, '$.role') = 'assistant'
    ) as api_call_count
from session s
order by s.time_updated desc
"""

_PARSE_SQL = """
select m.id as m_id, m.time_created as m_time, m.data as m_data,
       p.id as p_id, p.data as p_data
from message m
left join part p on p.message_id = m.id
where m.session_id = ?
order by m.time_created, m.id, p.id
"""

_TAIL_SQL = """
select m.data as m_data, p.data as p_data
from message m
join part p on p.message_id = m.id
where m.session_id = ?
  and json_extract(p.data, '$.type') = 'text'
order by m.time_created, m.id, p.id
"""


class OpencodeProvider(ProviderBase):
    @property
    def slug(self) -> str:
        return "opencode"

    @property
    def name(self) -> str:
        return "OpenCode"

    def default_paths(self) -> list[Path]:
        return [DEFAULT_DB_PATH]

    def discover_projects(self, paths: list[Path]) -> list[ProjectInfo]:
        projects_by_name: dict[str, ProjectInfo] = {}
        for db_path in _resolve_dbs(paths):
            rows = _discover_sessions(db_path)
            for row in rows:
                name = _project_name(row["directory"])
                if name not in projects_by_name:
                    projects_by_name[name] = ProjectInfo(
                        name=name,
                        path=Path(row["directory"]) if row["directory"] else db_path,
                        provider=self.slug,
                    )
                projects_by_name[name].sessions.append(SessionInfo(
                    session_id=row["id"],
                    path=db_path,
                    size_bytes=row["byte_count"] or 0,
                    mtime=(row["time_updated"] or 0) / 1000,
                    provider=self.slug,
                    cwd=row["directory"] or "",
                    title=row["title"] or "",
                    turn_count=row["turn_count"] or 0,
                    api_call_count=row["api_call_count"] or 0,
                ))

        for export_path in _resolve_json_exports(paths):
            session = _discover_json_export(export_path)
            if session is None:
                continue
            name = _project_name(session.cwd)
            if name not in projects_by_name:
                projects_by_name[name] = ProjectInfo(
                    name=name,
                    path=Path(session.cwd) if session.cwd else export_path.parent,
                    provider=self.slug,
                )
            if not any(
                item.session_id == session.session_id
                for item in projects_by_name[name].sessions
            ):
                projects_by_name[name].sessions.append(session)

        for project in projects_by_name.values():
            project.sessions.sort(key=lambda s: s.mtime, reverse=True)

        projects = list(projects_by_name.values())
        projects.sort(
            key=lambda p: max(s.mtime for s in p.sessions), reverse=True,
        )
        return projects

    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        if path.suffix.lower() == ".json":
            return _parse_opencode_json_export(path, session_id)
        return _parse_opencode_session(path, session_id)

    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3, session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        if path.suffix.lower() == ".json":
            return _extract_opencode_json_export_tail(path, max_exchanges)
        return _extract_opencode_tail(path, session_id, max_exchanges)

    def get_pricing(self, model: str) -> ModelPricing | None:
        return _opencode_pricing(model)


def _resolve_dbs(paths: list[Path]) -> list[Path]:
    """Expand configured paths to validated opencode DB files.

    Each path may be a `.db` file or a directory (scanned for `*.db`).
    Files that aren't valid opencode databases are skipped.
    """
    dbs: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        candidates: list[Path]
        if p.is_file():
            candidates = [p]
        elif p.is_dir():
            candidates = sorted(p.glob("*.db"))
        else:
            continue
        for db in candidates:
            if not _is_opencode_db(db):
                continue
            resolved = db.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            dbs.append(db)
    return dbs


def _resolve_json_exports(paths: list[Path]) -> list[Path]:
    """Find OpenCode JSON exports from configured files or directories."""
    exports: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.is_file():
            candidates = [path] if path.suffix.lower() == ".json" else []
        elif path.is_dir():
            candidates = sorted(path.rglob("*ses_*.json"))
        else:
            candidates = []

        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not candidate.is_file():
                continue
            if _read_opencode_json_export(candidate) is None:
                continue
            seen.add(resolved)
            exports.append(candidate)
    return exports


def _is_opencode_db(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return False
    try:
        tables = {
            r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        return all(t in tables for t in _REQUIRED_TABLES)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _read_opencode_json_export(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as export_file:
            data = json.load(export_file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    messages = data.get("messages")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("id"), str)
        or not isinstance(messages, list)
    ):
        return None
    return data


def _discover_json_export(path: Path) -> SessionInfo | None:
    data = _read_opencode_json_export(path)
    if data is None:
        return None
    info = data["info"]
    directory = info.get("directory", "")
    time_info = info.get("time", {})
    updated = time_info.get("updated") if isinstance(time_info, dict) else None
    try:
        mtime = int(updated) / 1000 if updated else path.stat().st_mtime
    except (OSError, TypeError, ValueError, OverflowError):
        mtime = path.stat().st_mtime

    turn_count = 0
    api_call_count = 0
    for message in data["messages"]:
        if not isinstance(message, dict):
            continue
        message_info = message.get("info", {})
        if not isinstance(message_info, dict):
            continue
        role = message_info.get("role", "")
        if role == "assistant":
            api_call_count += 1
        elif role == "user":
            parts = message.get("parts", [])
            if any(
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
                for part in parts
            ):
                turn_count += 1

    stat = path.stat()
    return SessionInfo(
        session_id=info["id"],
        path=path,
        size_bytes=stat.st_size,
        mtime=mtime,
        provider="opencode",
        cwd=directory if isinstance(directory, str) else "",
        title=info.get("title", "") if isinstance(info.get("title"), str) else "",
        turn_count=turn_count,
        api_call_count=api_call_count,
    )


def _open_db(path: Path) -> sqlite3.Connection:
    """Open the DB read-only to avoid WAL contention with a running opencode."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _discover_sessions(db_path: Path) -> list[sqlite3.Row]:
    try:
        conn = _open_db(db_path)
    except sqlite3.Error:
        return []
    try:
        return conn.execute(_DISCOVER_SQL).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _parse_opencode_session(path: Path, session_id: str | None) -> Session:
    if not session_id:
        return Session(session_id=path.stem)

    session = Session(session_id=session_id)
    try:
        conn = _open_db(path)
    except sqlite3.Error:
        return session

    try:
        meta = conn.execute(
            "select model, title, directory from session where id = ?",
            (session_id,),
        ).fetchone()
        if meta:
            session.model = _model_from_json(meta["model"])
            session.metadata = {
                "title": meta["title"] or "",
                "directory": meta["directory"] or "",
            }

        rows = conn.execute(_PARSE_SQL, (session_id,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    buffer: list[Message] = []
    turn_number = 0

    for m_id, group in _group_rows(rows):
        msgs = _parse_message_row(group)
        if not msgs:
            continue
        if any(m.role == "user" and m.content.strip() for m in msgs):
            if buffer:
                turn_number += 1
                session.turns.append(Turn(
                    number=turn_number,
                    messages=buffer,
                ))
            buffer = []
        buffer.extend(msgs)

    if buffer:
        turn_number += 1
        session.turns.append(Turn(
            number=turn_number,
            messages=buffer,
        ))

    return session


def _parse_opencode_json_export(
    path: Path,
    session_id: str | None,
) -> Session:
    data = _read_opencode_json_export(path)
    if data is None:
        return Session(session_id=session_id or path.stem)

    info = data["info"]
    export_id = info.get("id", "")
    session = Session(session_id=export_id or session_id or path.stem)
    session.model = _model_from_json(info.get("model", ""))
    session.metadata = {
        "title": info.get("title", "") or "",
        "directory": info.get("directory", "") or "",
        "source_format": "json_export",
    }

    buffer: list[Message] = []
    turn_number = 0
    for message in data["messages"]:
        parsed_messages = _parse_opencode_export_message(message)
        if not parsed_messages:
            continue
        if any(
            item.role == "user" and item.content.strip()
            for item in parsed_messages
        ):
            if buffer:
                turn_number += 1
                session.turns.append(Turn(
                    number=turn_number,
                    messages=buffer,
                ))
            buffer = []
        buffer.extend(parsed_messages)

    if buffer:
        turn_number += 1
        session.turns.append(Turn(number=turn_number, messages=buffer))
    return session


def _parse_opencode_export_message(message: dict[str, Any]) -> list[Message]:
    message_info = message.get("info", {})
    if not isinstance(message_info, dict):
        return []
    role = message_info.get("role", "")
    message_id = message_info.get("id", "")
    time_info = message_info.get("time", {})
    timestamp = _iso_ms(
        time_info.get("created") if isinstance(time_info, dict) else None,
    )
    raw_base: dict[str, Any] = {
        "timestamp": timestamp,
        "id": message_id,
        "role": role,
    }
    if role == "assistant":
        raw_base["requestId"] = message_id

    model_id = message_info.get("modelID", "")
    provider_id = message_info.get("providerID", "")
    model = _model_str(model_id, provider_id)
    usage = _usage_from(message_info)
    output: list[Message] = []

    parts = message.get("parts", [])
    if not isinstance(parts, list):
        return []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type", "")
        raw = dict(raw_base)

        if part_type == "text":
            text = part.get("text", "")
            if isinstance(text, str) and text.strip():
                output.append(Message(
                    role=role or "user",
                    content=text,
                    raw=raw,
                ))
        elif part_type == "reasoning":
            text = part.get("text", "")
            if isinstance(text, str) and text.strip():
                output.append(Message(
                    role="assistant",
                    content=f"[thinking] {text}",
                    raw=raw,
                ))
        elif part_type == "tool":
            tool_name = part.get("tool", "")
            call_id = part.get("callID", "")
            state = part.get("state", {})
            if not isinstance(state, dict):
                state = {}
            tool_input = state.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {"raw": str(tool_input)}
            output.append(Message(
                role="assistant",
                tool_calls=[ToolCall(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_id=call_id,
                )],
                raw=raw,
            ))
            tool_output, is_error = _tool_output(state)
            output.append(Message(
                role="tool_result",
                tool_results=[ToolResult(
                    tool_name=tool_name,
                    output=tool_output,
                    tool_id=call_id,
                    is_error=is_error,
                )],
                raw=raw,
            ))

    if output and usage:
        output[0].usage = usage
        if model and not output[0].model:
            output[0].model = model
    return output


def _group_rows(rows: list[sqlite3.Row]) -> Iterator[tuple[Any, Any]]:
    current_id = None
    current: list[sqlite3.Row] = []
    for row in rows:
        if row["m_id"] != current_id:
            if current:
                yield current_id, current
            current_id = row["m_id"]
            current = []
        current.append(row)
    if current:
        yield current_id, current


def _parse_message_row(rows: list[sqlite3.Row]) -> list[Message]:
    mrow = rows[0]
    m_data = _json(mrow["m_data"])
    if not m_data:
        return []
    role = m_data.get("role", "")
    iso = _iso_ms(mrow["m_time"])
    raw_base: dict[str, Any] = {
        "timestamp": iso,
        "id": mrow["m_id"],
        "role": role,
    }
    if role == "assistant":
        raw_base["requestId"] = mrow["m_id"]
    model = _model_str(
        m_data.get("modelID", ""), m_data.get("providerID", ""),
    )
    usage = _usage_from(m_data)

    out: list[Message] = []
    for prow in rows:
        if not prow["p_id"]:
            continue
        part = _json(prow["p_data"])
        if not part:
            continue
        ptype = part.get("type", "")
        raw = dict(raw_base)

        if ptype == "text":
            text = part.get("text", "")
            if not isinstance(text, str) or not text.strip():
                continue
            out.append(Message(
                role=role or "user", content=text, raw=raw,
            ))
        elif ptype == "reasoning":
            text = part.get("text", "")
            if isinstance(text, str) and text.strip():
                out.append(Message(
                    role="assistant", content=f"[thinking] {text}", raw=raw,
                ))
        elif ptype == "tool":
            tool_name = part.get("tool", "")
            call_id = part.get("callID", "")
            state = part.get("state", {})
            if not isinstance(state, dict):
                state = {}
            tool_input = state.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {"raw": str(tool_input)}
            out.append(Message(
                role="assistant",
                tool_calls=[ToolCall(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_id=call_id,
                )],
                raw=raw,
            ))
            output, is_error = _tool_output(state)
            out.append(Message(
                role="tool_result",
                tool_results=[ToolResult(
                    tool_name=tool_name,
                    output=output,
                    tool_id=call_id,
                    is_error=is_error,
                )],
                raw=raw,
            ))
        # step-start / step-finish carry no displayable content

    if out and usage:
        out[0].usage = usage
        if model and not out[0].model:
            out[0].model = model
    return out


def _tool_output(state: dict) -> tuple[str, bool]:
    status = state.get("status", "")
    if status == "error":
        err = state.get("error", "")
        if isinstance(err, list):
            err = _extract_opencode_text(err)
        return str(err or "error"), True
    if status in ("pending", "running"):
        return "(in progress)", False
    out = state.get("output", "")
    if out is None:
        return "", False
    if isinstance(out, list):
        out = _extract_opencode_text(out)
    elif not isinstance(out, str):
        out = json.dumps(out, indent=2, ensure_ascii=False)
    return out, False


def _extract_opencode_text(content: list) -> str:
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") in ("text", "input_text", "output_text"):
                parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p)


def _extract_opencode_tail(
    path: Path, session_id: str | None, max_exchanges: int = 3,
) -> list[tuple[str, str]]:
    if not session_id:
        return []
    user_texts: list[str] = []
    assistant_texts: list[str] = []
    try:
        conn = _open_db(path)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(_TAIL_SQL, (session_id,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    for row in rows:
        m_data = _json(row["m_data"])
        role = m_data.get("role", "") if m_data else ""
        text = _json(row["p_data"]).get("text", "")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        if role == "assistant":
            assistant_texts.append(text)
        elif role == "user":
            user_texts.append(text)

    messages: list[tuple[str, str]] = []
    for i in range(min(len(user_texts), len(assistant_texts))):
        messages.append((user_texts[i], assistant_texts[i]))
    if len(user_texts) > len(assistant_texts):
        messages.append((user_texts[-1], ""))
    return messages[-max_exchanges:]


def _extract_opencode_json_export_tail(
    path: Path,
    max_exchanges: int,
) -> list[tuple[str, str]]:
    session = _parse_opencode_json_export(path, None)
    exchanges: list[tuple[str, str]] = []
    for turn in session.turns:
        user_text = next(
            (m.content for m in turn.messages if m.role == "user" and m.content),
            "",
        )
        assistant_texts = [
            m.content
            for m in turn.messages
            if m.role == "assistant" and m.content
            and not m.content.startswith("[thinking] ")
        ]
        if user_text or assistant_texts:
            exchanges.append((user_text, assistant_texts[-1] if assistant_texts else ""))
    return exchanges[-max_exchanges:]


def _opencode_pricing(model: str) -> ModelPricing | None:
    """Map opencode's `provider/model` strings onto known pricing tables."""
    provider, _, model_id = model.partition("/")
    if provider == "anthropic":
        return get_pricing(model_id)
    if provider == "openai":
        return get_codex_pricing(model_id)
    return None


def _model_str(model_id: str, provider_id: str) -> str:
    if not model_id:
        return ""
    return f"{provider_id}/{model_id}" if provider_id else model_id


def _model_from_json(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(value, dict):
        return _model_str(
            value.get("id", ""), value.get("providerID", ""),
        )
    return str(value)


def _usage_from(m_data: dict) -> dict[str, int]:
    tokens = m_data.get("tokens")
    if not isinstance(tokens, dict):
        return {}
    cache = tokens.get("cache")
    if not isinstance(cache, dict):
        cache = {}
    return {
        "input_tokens": int(tokens.get("input", 0) or 0),
        "output_tokens": int(tokens.get("output", 0) or 0),
        "reasoning_tokens": int(tokens.get("reasoning", 0) or 0),
        "cache_read_input_tokens": int(cache.get("read", 0) or 0),
        "cache_creation_input_tokens": int(cache.get("write", 0) or 0),
    }


def _iso_ms(ms: Any) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _project_name(directory: str) -> str:
    if not directory:
        return "unknown"
    name = Path(directory).name
    return name or directory


def _json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        obj = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}
