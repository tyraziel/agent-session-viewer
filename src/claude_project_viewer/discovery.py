"""Discover Claude Code projects and sessions from ~/.claude/projects/."""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

ACTIVE_THRESHOLD_SECONDS = 900


PROVIDER_RESUME_COMMANDS = {
    "claude": "claude --resume {session_id}",
    "codex": "codex --resume {session_id}",
    "opencode": "opencode -s {session_id}",
}

PROVIDER_COLORS = {
    "claude": "deep-orange",
    "codex": "teal",
    "opencode": "indigo",
}


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    size_bytes: int
    mtime: float
    provider: str = "claude"
    cwd: str = ""
    title: str = ""
    turn_count: int = 0
    api_call_count: int = 0

    @property
    def display_name(self) -> str:
        return self.session_id

    @property
    def is_active(self) -> bool:
        return (time.time() - self.mtime) < ACTIVE_THRESHOLD_SECONDS

    @property
    def resume_command(self) -> str:
        parts = []
        if self.cwd:
            parts.append(f"cd {self.cwd}")
        template = PROVIDER_RESUME_COMMANDS.get(
            self.provider, "claude --resume {session_id}",
        )
        parts.append(template.format(session_id=self.session_id))
        return " && ".join(parts)


@dataclass
class ProjectInfo:
    name: str
    path: Path
    provider: str = "claude"
    sessions: list[SessionInfo] = field(default_factory=list)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def has_active_session(self) -> bool:
        return any(s.is_active for s in self.sessions)

    @property
    def active_session_count(self) -> int:
        return sum(1 for s in self.sessions if s.is_active)


@dataclass
class HistoryFile:
    path: Path
    size_bytes: int
    mtime: float


def get_claude_base_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def discover_history(base_dir: Path | None = None) -> HistoryFile | None:
    if base_dir is None:
        base_dir = get_claude_base_dir()
    history = base_dir / "history.jsonl"
    if history.is_file():
        stat = history.stat()
        return HistoryFile(path=history, size_bytes=stat.st_size, mtime=stat.st_mtime)
    return None


def discover_all_projects() -> list[ProjectInfo]:
    """Discover projects from all registered providers."""
    from claude_project_viewer.app import get_config
    from claude_project_viewer.config import resolve_provider_paths
    from claude_project_viewer.providers import get_all_providers

    config = get_config()
    all_projects: list[ProjectInfo] = []

    for provider in get_all_providers():
        paths = resolve_provider_paths(config, provider.slug, provider.default_paths())
        if not paths:
            continue
        projects = provider.discover_projects(paths)
        all_projects.extend(projects)

    all_projects.sort(
        key=lambda p: max(s.mtime for s in p.sessions) if p.sessions else 0,
        reverse=True,
    )
    return all_projects


def discover_projects(
    project_dirs: list[Path] | None = None,
    base_dir: Path | None = None,
) -> list[ProjectInfo]:
    if project_dirs is not None:
        dirs = project_dirs
    else:
        if base_dir is None:
            base_dir = get_claude_base_dir()
        dirs = [base_dir / "projects"]

    projects_by_name: dict[str, ProjectInfo] = {}
    for projects_dir in dirs:
        if not projects_dir.is_dir():
            continue
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            sessions = _discover_sessions(entry)
            if sessions:
                if entry.name in projects_by_name:
                    projects_by_name[entry.name].sessions.extend(sessions)
                    projects_by_name[entry.name].sessions.sort(
                        key=lambda s: s.mtime, reverse=True,
                    )
                else:
                    projects_by_name[entry.name] = ProjectInfo(
                        name=entry.name,
                        path=entry,
                        sessions=sessions,
                    )

    projects = list(projects_by_name.values())
    projects.sort(key=lambda p: max(s.mtime for s in p.sessions), reverse=True)
    return projects


def _discover_sessions(project_dir: Path) -> list[SessionInfo]:
    sessions = []
    for f in project_dir.iterdir():
        if f.suffix == ".jsonl" and f.is_file():
            stat = f.stat()
            cwd, title = _extract_session_meta(f)
            turn_count, api_call_count = _count_turns_and_api_calls(f)
            sessions.append(SessionInfo(
                session_id=f.stem,
                path=f,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                cwd=cwd,
                title=title,
                turn_count=turn_count,
                api_call_count=api_call_count,
            ))
    sessions.sort(key=lambda s: s.mtime, reverse=True)
    return sessions


@dataclass
class ActiveSessionInfo:
    session: SessionInfo
    project_name: str
    exchanges: list[tuple[str, str]] = field(default_factory=list)


def discover_active_sessions(
    projects: list[ProjectInfo] | None = None,
    threshold: float = ACTIVE_THRESHOLD_SECONDS,
) -> list["ActiveSessionInfo"]:
    from claude_project_viewer.providers import get_provider

    if projects is None:
        projects = discover_all_projects()
    active = []
    for project in projects:
        for session in project.sessions:
            if (time.time() - session.mtime) < threshold:
                provider = get_provider(session.provider)
                if provider:
                    exchanges = provider.extract_tail_exchanges(
                        session.path, session_id=session.session_id,
                    )
                else:
                    exchanges = _extract_tail_exchanges(session.path)
                active.append(ActiveSessionInfo(
                    session=session,
                    project_name=project.name,
                    exchanges=exchanges,
                ))
    active.sort(key=lambda a: a.session.mtime, reverse=True)
    return active


def _extract_tail_exchanges(
    path: Path, max_exchanges: int = 3,
) -> list[tuple[str, str]]:
    """Read the tail of a JSONL and return the last few (user, assistant) pairs."""
    messages: list[tuple[str, str]] = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk_size = min(size, 65536)
            f.seek(size - chunk_size)
            data = f.read().decode("utf-8", errors="replace")

        user_texts: list[str] = []
        assistant_texts: list[str] = []

        for raw_line in reversed(data.strip().split("\n")):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            line_type = obj.get("type", "")
            text = _extract_line_text(obj, line_type)
            if not text:
                continue

            if line_type == "assistant":
                assistant_texts.append(text)
            elif line_type in ("user", "queue-operation"):
                user_texts.append(text)

            if len(user_texts) >= max_exchanges and len(assistant_texts) >= max_exchanges:
                break

        user_texts.reverse()
        assistant_texts.reverse()
        for i in range(min(len(user_texts), len(assistant_texts))):
            messages.append((user_texts[i], assistant_texts[i]))
        if len(user_texts) > len(assistant_texts):
            messages.append((user_texts[-1], ""))

    except OSError:
        pass
    return messages[-max_exchanges:]


def _extract_line_text(obj: dict, line_type: str) -> str:
    if line_type == "assistant":
        msg = obj.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        return text
    elif line_type == "user":
        msg = obj.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            if "<task-notification>" not in content:
                return content.strip()
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text and "<task-notification>" not in text:
                        return text
    elif line_type == "queue-operation" and obj.get("operation") == "enqueue":
        content = obj.get("content", "")
        if isinstance(content, str) and content.strip():
            if "<task-notification>" not in content:
                return content.strip()
    return ""


def _count_turns_and_api_calls(path: Path) -> tuple[int, int]:
    """Count turns (user messages with text) and API calls (unique requestIds).

    Matches the parser's turn-splitting logic: every user message or
    queue-operation enqueue with text content starts a new turn.
    """
    turns = 0
    request_ids: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '"type":"assistant"' in line:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "assistant":
                        rid = obj.get("requestId", "")
                        if rid:
                            request_ids.add(rid)
                elif '"type":"user"' in line:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "user":
                        continue
                    origin = obj.get("origin", {})
                    if origin.get("kind") == "task-notification":
                        continue
                    msg = obj.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        if "<task-notification>" not in content:
                            turns += 1
                    elif isinstance(content, list):
                        has_text = any(
                            isinstance(b, dict)
                            and b.get("type") == "text"
                            and b.get("text", "").strip()
                            for b in content
                            if isinstance(b, dict) and b.get("type") != "tool_result"
                        )
                        if has_text:
                            turns += 1
                elif '"queue-operation"' in line:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (obj.get("type") == "queue-operation"
                            and obj.get("operation") == "enqueue"):
                        content = obj.get("content", "")
                        if (isinstance(content, str) and content.strip()
                                and "<task-notification>" not in content):
                            turns += 1
    except OSError:
        pass
    return turns, len(request_ids)


def _extract_session_meta(path: Path) -> tuple[str, str]:
    cwd = ""
    title = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if cwd and title:
                    break
                if i > 50:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if not cwd:
                        cwd = obj.get("cwd", "")
                    if obj.get("type") == "ai-title":
                        title = obj.get("aiTitle", "")
                    if obj.get("type") == "session-name":
                        title = obj.get("name", "") or title
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return cwd, title
