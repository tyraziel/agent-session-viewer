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


def discover_projects(base_dir: Path | None = None) -> list[ProjectInfo]:
    if base_dir is None:
        base_dir = get_claude_base_dir()

    projects_dir = base_dir / "projects"
    if not projects_dir.is_dir():
        return []

    projects = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        sessions = _discover_sessions(entry)
        if sessions:
            projects.append(ProjectInfo(
                name=entry.name,
                path=entry,
                sessions=sessions,
            ))

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
