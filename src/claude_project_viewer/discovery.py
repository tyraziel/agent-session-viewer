"""Discover Claude Code projects and sessions from ~/.claude/projects/."""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

ACTIVE_THRESHOLD_SECONDS = 900


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    size_bytes: int
    mtime: float
    cwd: str = ""
    title: str = ""

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
        parts.append(f"claude --resume {self.session_id}")
        return " && ".join(parts)


@dataclass
class ProjectInfo:
    name: str
    path: Path
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
            sessions.append(SessionInfo(
                session_id=f.stem,
                path=f,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                cwd=cwd,
                title=title,
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
    if projects is None:
        projects = discover_projects()
    active = []
    for project in projects:
        for session in project.sessions:
            if (time.time() - session.mtime) < threshold:
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
