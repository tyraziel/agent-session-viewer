"""Claude Code session provider."""

import json
import re
from pathlib import Path

from agent_session_viewer.config import SessionPath, normalize_session_path
from agent_session_viewer.discovery import (
    ProjectInfo,
    SessionInfo,
    _count_turns_and_api_calls,
    _extract_session_meta,
    _extract_tail_exchanges,
    file_content_hash,
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

    def discover_projects(
        self, paths: list[Path | SessionPath],
    ) -> list[ProjectInfo]:
        projects_by_name: dict[str, ProjectInfo] = {}
        seen_sessions: set[Path] = set()

        def add_sessions(name: str, path: Path, sessions: list[SessionInfo]):
            new_sessions = []
            for session in sessions:
                resolved = session.path.resolve()
                if resolved not in seen_sessions:
                    seen_sessions.add(resolved)
                    new_sessions.append(session)
            if not new_sessions:
                return
            if name in projects_by_name:
                projects_by_name[name].sessions.extend(new_sessions)
                projects_by_name[name].sessions.sort(
                    key=lambda s: s.mtime, reverse=True,
                )
            else:
                projects_by_name[name] = ProjectInfo(
                    name=name,
                    path=path,
                    provider=self.slug,
                    sessions=new_sessions,
                )

        for path_entry in paths:
            spec = normalize_session_path(path_entry)
            projects_dir = spec.path
            seen_hashes: set[str] = set()

            def is_duplicate(transcript: Path) -> bool:
                if not spec.deduplicate:
                    return False
                digest = file_content_hash(transcript)
                if digest is None:
                    return False
                if digest in seen_hashes:
                    return True
                seen_hashes.add(digest)
                return False

            if projects_dir.is_file():
                if (
                    projects_dir.suffix == ".jsonl"
                    and _is_claude_session_file(projects_dir)
                    and not is_duplicate(projects_dir)
                ):
                    session = self._session_info(projects_dir)
                    slug = _claude_cwd_to_slug(session.cwd) if session.cwd else projects_dir.parent.name
                    project_path = Path(session.cwd) if session.cwd else projects_dir.parent
                    add_sessions(slug, project_path, [session])
                continue

            if not projects_dir.is_dir():
                continue

            if spec.recursive is True:
                for transcript in projects_dir.rglob("*.jsonl"):
                    if (
                        not _is_claude_session_file(transcript)
                        or is_duplicate(transcript)
                    ):
                        continue
                    session = self._session_info(transcript)
                    slug = (
                        _claude_cwd_to_slug(session.cwd)
                        if session.cwd
                        else _claude_cwd_to_slug(str(transcript.parent))
                    )
                    project_path = (
                        Path(session.cwd) if session.cwd else transcript.parent
                    )
                    add_sessions(slug, project_path, [session])
                continue

            direct_files = [
                transcript for transcript in projects_dir.iterdir()
                if transcript.is_file()
                and transcript.suffix == ".jsonl"
                and _is_claude_session_file(transcript)
            ]
            if direct_files:
                for transcript in direct_files:
                    if is_duplicate(transcript):
                        continue
                    session = self._session_info(transcript)
                    slug = (
                        _claude_cwd_to_slug(session.cwd)
                        if session.cwd
                        else projects_dir.name
                    )
                    project_path = (
                        Path(session.cwd) if session.cwd else projects_dir
                    )
                    add_sessions(slug, project_path, [session])
                if spec.recursive is False:
                    continue
            elif spec.recursive is False:
                continue

            for entry in sorted(projects_dir.iterdir()):
                if not entry.is_dir():
                    continue
                sessions = [
                    session for session in self._discover_sessions(entry)
                    if not is_duplicate(session.path)
                ]
                if sessions:
                    add_sessions(entry.name, entry, sessions)
        projects = list(projects_by_name.values())
        projects.sort(
            key=lambda p: max(s.mtime for s in p.sessions), reverse=True,
        )
        return projects

    def _discover_sessions(self, project_dir: Path) -> list[SessionInfo]:
        sessions = []
        for f in project_dir.iterdir():
            if f.suffix == ".jsonl" and f.is_file():
                sessions.append(self._session_info(f))
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions

    def _session_info(self, path: Path) -> SessionInfo:
        stat = path.stat()
        cwd, title = _extract_session_meta(path)
        turn_count, api_call_count = _count_turns_and_api_calls(path)
        return SessionInfo(
            session_id=path.stem,
            path=path,
            size_bytes=stat.st_size,
            mtime=stat.st_mtime,
            provider=self.slug,
            cwd=cwd,
            title=title,
            turn_count=turn_count,
            api_call_count=api_call_count,
        )

    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        return parse_session(path)

    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3, session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        return _extract_tail_exchanges(path, max_exchanges)

    def get_pricing(self, model: str) -> ModelPricing | None:
        return get_pricing(model)


def _is_claude_session_file(path: Path) -> bool:
    """Avoid classifying other providers' JSONL files as Claude sessions."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for index, line in enumerate(f):
                if index >= 100:
                    break
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(obj, dict)
                    and obj.get("type") in ("user", "assistant")
                    and isinstance(obj.get("message"), dict)
                ):
                    return True
    except OSError:
        return False
    return False


def _claude_cwd_to_slug(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)
