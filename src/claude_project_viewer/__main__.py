"""Entry point for claude-project-viewer."""

import argparse
import os

from nicegui import ui

from claude_project_viewer.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Claude Project Viewer")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--claude-dir",
        default=None,
        help="Path to Claude config directory (default: ~/.claude or CLAUDE_CONFIG_DIR)",
    )
    args = parser.parse_args()

    if args.claude_dir:
        os.environ["CLAUDE_CONFIG_DIR"] = args.claude_dir

    create_app()
    ui.run(
        title="Claude Project Viewer",
        port=args.port,
        host=args.host,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
