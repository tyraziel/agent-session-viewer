"""Entry point for agent-session-viewer."""

import argparse
import logging
import os
from pathlib import Path

from nicegui import ui

from agent_session_viewer.app import create_app
from agent_session_viewer.config import load_config
from agent_session_viewer.providers import register_provider
from agent_session_viewer.providers.claude import ClaudeProvider
from agent_session_viewer.providers.codex import CodexProvider
from agent_session_viewer.providers.opencode import OpencodeProvider


def main():
    parser = argparse.ArgumentParser(description="Agent Session Viewer")
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
        help="Path to config file (default: ~/.config/agent-session-viewer/config.json)",
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

    register_provider(ClaudeProvider())
    register_provider(CodexProvider())
    register_provider(OpencodeProvider())

    create_app(config=config)
    ui.run(
        title="Agent Session Viewer",
        port=args.port,
        host=args.host,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
