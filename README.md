# Claude Code Project Viewer

A pure Python web UI for browsing Claude Code conversation history, project memories, and prompt history. Built with [NiceGUI](https://nicegui.io/).

Web UI patterns adopted from [ai-guardian](https://github.com/RedHatProductSecurity/ai-guardian)'s trace viewer.

## Features

- **Project Browser** — Scans `~/.claude/projects/` and lists all projects with session counts, sizes, and last-activity times. Auto-refreshes when files change on disk.
- **Session Viewer** — Turn-by-turn conversation viewer with inline recap (your prompt + Claude's response) and expandable full details showing all tool calls, results, and system messages.
- **Prompt History** — Browse `~/.claude/history.jsonl` with filtering by project and text search. Entries with session IDs link directly to the session viewer.
- **Memory Viewer** — Browse project-level memories grouped by type (user, feedback, project, reference) with YAML frontmatter parsing.
- **Activity Indicators** — Pulsing colored dot shows session recency: green (<5 min), yellow (5-10 min), orange (10-20 min).
- **Resume Commands** — Copy-pasteable `cd <dir> && claude --resume <id>` command on every session, with one-click clipboard copy.
- **Session Titles** — Shows AI-generated or user-set session names alongside UUIDs.
- **Live Updates** — Polls for file changes and auto-refreshes the view, including during active sessions.

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone and install
git clone <repo-url>
cd claude-code-project-viewer
uv sync

# Run
uv run claude-project-viewer
```

Open http://127.0.0.1:8090 in your browser.

## CLI Options

```
uv run claude-project-viewer [OPTIONS]

Options:
  --port PORT        Port to serve on (default: 8090)
  --host HOST        Host to bind to (default: 127.0.0.1)
  --claude-dir DIR   Path to Claude config directory (default: ~/.claude)
```

The `--claude-dir` flag overrides the default `~/.claude` location. You can also set the `CLAUDE_CONFIG_DIR` environment variable.

## How It Works

Claude Code stores conversation transcripts as JSONL files in `~/.claude/projects/<project-slug>/<session-id>.jsonl`, where `<project-slug>` is your working directory path with non-alphanumeric characters replaced by dashes. Each line is a JSON object representing a message, tool call, or metadata entry.

The viewer:

1. **Discovery** — Scans the projects directory for JSONL session files and extracts lightweight metadata (cwd, session title) from the first few lines of each file.
2. **Parsing** — Reads the full JSONL on demand, classifies each line by type (`user`, `assistant`, `tool_result`, `queue-operation`, etc.), and groups them into turns. Tool results masquerading as user messages are correctly identified and separated from actual human input. Mid-turn user messages (sent while Claude is working) are captured from `queue-operation` entries.
3. **Rendering** — NiceGUI serves a web UI with project list, session list, and session detail pages. Each turn shows an inline conversation recap with the full message details available in an expandable section.

## Project Structure

```
src/claude_project_viewer/
├── __init__.py
├── __main__.py          # CLI entry point
├── app.py               # NiceGUI routes
├── discovery.py         # Project/session/history file discovery
├── formatting.py        # Display helpers (time ago, file size, activity)
├── parser.py            # JSONL session parser
└── pages/
    ├── history.py       # Prompt history page
    ├── memory.py        # Project memory viewer
    ├── projects.py      # Project listing page
    ├── session_detail.py # Turn-by-turn session viewer
    └── session_list.py  # Session listing for a project
```

## AI Attribution

[AIA PAI SeCeNc Hin R Claude Code \[Opus 4.6 1m\] v1.0](https://aiattribution.github.io/statements/AIA-PAI-SeCeNc-Hin-R-?model=Claude%20Code%20%5BOpus%204.6%201m%5D-v1.0)

This work was primarily AI-generated. AI was used to make stylistic edits, such as changes to structure, wording, and clarity. AI was used to make content edits, such as changes to scope, information, and ideas. AI was used to make new content, such as text, images, analysis, and ideas. AI was prompted for its contributions, or AI assistance was enabled. AI-generated content was reviewed and approved. The following model(s) or application(s) were used: Claude Code [Opus 4.6 1m].

## License

See [LICENSE](LICENSE).
