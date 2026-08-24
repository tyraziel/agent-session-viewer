"""Entry point for claude-project-viewer."""

import argparse
import logging
import os
from pathlib import Path

from nicegui import ui

from claude_project_viewer.app import create_app
from claude_project_viewer.config import load_config, resolve_session_paths


def main():
    parser = argparse.ArgumentParser(description="Claude Project Viewer")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--claude-dir",
        default=None,
        help="Path to Claude config directory (default: ~/.claude or CLAUDE_CONFIG_DIR)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config file (default: ~/.config/claude-project-viewer/config.json)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.claude_dir:
        os.environ["CLAUDE_CONFIG_DIR"] = args.claude_dir

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    session_paths = resolve_session_paths(config)

    create_app(session_paths=session_paths or None)
    ui.run(
        title="Claude Project Viewer",
        port=args.port,
        host=args.host,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
