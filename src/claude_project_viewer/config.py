"""Configuration for claude-project-viewer."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("claude_project_viewer")

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "claude-project-viewer" / "config.json"

_session_paths: list[Path] | None = None


def get_session_paths() -> list[Path] | None:
    return _session_paths


def set_session_paths(paths: list[Path]) -> None:
    global _session_paths
    _session_paths = paths


@dataclass
class Config:
    session_paths: list[Path] = field(default_factory=list)
    include_default: bool = True


def load_config(config_path: Path | None = None) -> Config:
    path = config_path or DEFAULT_CONFIG_PATH
    config = Config()

    if path.is_file():
        log.info("Loading config from %s", path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
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


def resolve_session_paths(config: Config) -> list[Path]:
    """Resolve the final list of directories to scan for projects."""
    paths: list[Path] = list(config.session_paths)

    claude_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")

    if config.include_default:
        if claude_config_dir:
            default_path = Path(claude_config_dir) / "projects"
            log.info(
                "Including CLAUDE_CONFIG_DIR projects: %s", default_path,
            )
            paths.append(default_path)
        else:
            default_path = Path.home() / ".claude" / "projects"
            log.info("Including default projects path: %s", default_path)
            paths.append(default_path)
    elif claude_config_dir:
        log.info(
            "CLAUDE_CONFIG_DIR is set (%s) but include_default is false, skipping",
            claude_config_dir,
        )

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
