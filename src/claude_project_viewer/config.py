"""Configuration for claude-project-viewer."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("claude_project_viewer")

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "claude-project-viewer" / "config.json"


@dataclass
class ProviderConfig:
    enabled: bool = True
    session_paths: list[Path] = field(default_factory=list)
    include_default: bool = True


@dataclass
class Config:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    # Legacy flat config (backwards compat)
    session_paths: list[Path] = field(default_factory=list)
    include_default: bool = True


def load_config(config_path: Path | None = None) -> Config:
    path = config_path or DEFAULT_CONFIG_PATH
    config = Config()

    if path.is_file():
        log.info("Loading config from %s", path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))

            if "providers" in raw:
                for slug, pconf in raw["providers"].items():
                    config.providers[slug] = ProviderConfig(
                        enabled=pconf.get("enabled", True),
                        session_paths=[
                            Path(p).expanduser()
                            for p in pconf.get("session_paths", [])
                        ],
                        include_default=pconf.get("include_default", True),
                    )
            else:
                if "session_paths" in raw:
                    config.session_paths = [
                        Path(p).expanduser() for p in raw["session_paths"]
                    ]
                if "include_default" in raw:
                    config.include_default = bool(raw["include_default"])
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load config from %s: %s", path, e)
    else:
        log.info("No config file at %s, using defaults", path)

    return config


def resolve_provider_paths(
    config: Config, provider_slug: str, default_paths: list[Path],
) -> list[Path]:
    """Resolve session paths for a specific provider."""
    pconf = config.providers.get(provider_slug)

    if pconf is not None:
        if not pconf.enabled:
            log.info("Provider %s is disabled", provider_slug)
            return []
        paths = list(pconf.session_paths)
        if pconf.include_default:
            if provider_slug == "claude":
                claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
                if claude_config_dir:
                    dp = Path(claude_config_dir) / "projects"
                    log.info("Including CLAUDE_CONFIG_DIR for %s: %s", provider_slug, dp)
                    paths.append(dp)
                else:
                    for dp in default_paths:
                        log.info("Including default path for %s: %s", provider_slug, dp)
                        paths.append(dp)
            else:
                for dp in default_paths:
                    log.info("Including default path for %s: %s", provider_slug, dp)
                    paths.append(dp)
        return _dedup(paths)

    # No per-provider config — use legacy flat config or defaults
    if config.session_paths and provider_slug == "claude":
        paths = list(config.session_paths)
        if config.include_default:
            claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
            if claude_config_dir:
                paths.append(Path(claude_config_dir) / "projects")
            else:
                paths.extend(default_paths)
        elif os.environ.get("CLAUDE_CONFIG_DIR"):
            log.info(
                "CLAUDE_CONFIG_DIR is set but include_default is false, skipping",
            )
        return _dedup(paths)

    # Default: use provider's built-in paths
    if provider_slug == "claude":
        claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if claude_config_dir:
            log.info("Including CLAUDE_CONFIG_DIR for %s: %s/projects", provider_slug, claude_config_dir)
            return [Path(claude_config_dir) / "projects"]
    for dp in default_paths:
        log.info("Including default path for %s: %s", provider_slug, dp)
    return list(default_paths)


def _dedup(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(p)
    for p in deduped:
        if p.is_dir():
            log.info("Scanning session path: %s", p)
        else:
            log.warning("Session path does not exist: %s", p)
    return deduped
