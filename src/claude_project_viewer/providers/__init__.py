"""Provider abstraction for multi-tool session viewing."""

from abc import ABC, abstractmethod
from pathlib import Path

from claude_project_viewer.discovery import ProjectInfo, SessionInfo
from claude_project_viewer.parser import Session
from claude_project_viewer.pricing import ModelPricing


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
    def discover_projects(self, paths: list[Path]) -> list[ProjectInfo]:
        """Discover projects from the given directories."""

    @abstractmethod
    def parse_session(self, path: Path) -> Session:
        """Full parse of a session file."""

    @abstractmethod
    def extract_tail_exchanges(
        self, path: Path, max_exchanges: int = 3,
    ) -> list[tuple[str, str]]:
        """Quick tail-read for active session cards."""

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
