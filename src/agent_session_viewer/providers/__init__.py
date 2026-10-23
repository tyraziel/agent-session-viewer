"""Provider abstraction for multi-tool session viewing."""

from abc import ABC, abstractmethod
from pathlib import Path

from agent_session_viewer.config import SessionPath
from agent_session_viewer.discovery import ProjectInfo, SessionInfo
from agent_session_viewer.parser import Session
from agent_session_viewer.pricing import ModelPricing


class ProviderBase(ABC):
    @property
    @abstractmethod
    def slug(self) -> str:
        """URL-safe identifier (e.g. 'claude', 'codex')."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name (e.g. 'Claude', 'Codex')."""

    @abstractmethod
    def default_paths(self) -> list[Path]:
        """Default session directories when none configured."""

    @abstractmethod
    def discover_projects(
        self, paths: list[Path | SessionPath],
    ) -> list[ProjectInfo]:
        """Discover projects from the given directories."""

    @abstractmethod
    def parse_session(self, path: Path, session_id: str | None = None) -> Session:
        """Full parse of a session.

        ``session_id`` disambiguates sessions stored together (e.g. one
        SQLite DB holding many sessions); file-based providers ignore it.
        """

    @abstractmethod
    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3, session_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Quick tail-read for active session cards."""

    def get_session_revision(
        self, path: Path, session_id: str | None = None,
    ) -> tuple[int, ...] | None:
        """Return a cheap change token for polling a session transcript."""
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def get_session_mtime(
        self, path: Path, session_id: str | None = None,
    ) -> float:
        """Return the session's last-activity time for the detail header."""
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def get_pricing(self, model: str) -> ModelPricing | None:
        """Return pricing for a model, or None if unknown."""
        return None


_registry: dict[str, ProviderBase] = {}


def register_provider(provider: ProviderBase) -> None:
    _registry[provider.slug] = provider


def get_provider(slug: str) -> ProviderBase | None:
    return _registry.get(slug)


def get_all_providers() -> list[ProviderBase]:
    return list(_registry.values())
