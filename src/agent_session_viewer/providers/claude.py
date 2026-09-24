"""Claude Code session provider."""

from pathlib import Path

from agent_session_viewer.discovery import (
    ProjectInfo,
    SessionInfo,
    _count_turns_and_api_calls,
    _extract_session_meta,
    _extract_tail_exchanges,
)
from agent_session_viewer.parser import Session, parse_session
from agent_session_viewer.pricing import ModelPricing, get_pricing
from agent_session_viewer.providers import ProviderBase


class ClaudeProvider(ProviderBase):
    @property
    def slug(self) -> str:
        return "claude"

    @property
    def name(self) -> str:
        return "Claude"

    def default_paths(self) -> list[Path]:
        return [Path.home() / ".claude" / "projects"]

    def discover_projects(self, paths: list[Path]) -> list[ProjectInfo]:
        projects_by_name: dict[str, ProjectInfo] = {}
        for projects_dir in paths:
            if not projects_dir.is_dir():
                continue
            for entry in sorted(projects_dir.iterdir()):
                if not entry.is_dir():
                    continue
                sessions = self._discover_sessions(entry)
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
                            provider=self.slug,
                            sessions=sessions,
                        )
        projects = list(projects_by_name.values())
        projects.sort(
            key=lambda p: max(s.mtime for s in p.sessions), reverse=True,
        )
        return projects

    def _discover_sessions(self, project_dir: Path) -> list[SessionInfo]:
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
                    provider=self.slug,
                    cwd=cwd,
                    title=title,
                    turn_count=turn_count,
                    api_call_count=api_call_count,
                ))
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions

    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        return parse_session(path)

    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3, session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        return _extract_tail_exchanges(path, max_exchanges)

    def get_pricing(self, model: str) -> ModelPricing | None:
        return get_pricing(model)
