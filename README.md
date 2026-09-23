# Agent Session Viewer

A pure Python web UI for browsing sessions, project memories, and prompt history from AI coding agent CLIs. Built with [NiceGUI](https://nicegui.io/).

Supports **Claude Code**, **Codex CLI**, and **OpenCode** out of the box, with a provider abstraction for adding more.

Web UI patterns adopted from [ai-guardian](https://github.com/RedHatProductSecurity/ai-guardian)'s trace viewer.

## Features

- **Project Browser** — Lists all projects across every enabled provider with session counts, sizes, last-activity times, and provider badges. Auto-refreshes when sessions change on disk.
- **Session Viewer** — Turn-by-turn conversation viewer with inline recap (your prompt + the agent's response) and expandable full details showing all tool calls, results, thinking blocks, and system messages.
- **Multi-Provider** — Claude Code, Codex CLI, and OpenCode sessions are discovered, parsed, and rendered through a shared provider abstraction; each provider keeps its own storage format, resume commands, and pricing.
- **Prompt History** — Browse `~/.claude/history.jsonl` with filtering by project and text search. Entries with session IDs link directly to the session viewer.
- **Memory Viewer** — Browse Claude project-level memories grouped by type (user, feedback, project, reference) with YAML frontmatter parsing.
- **Activity Indicators** — Pulsing colored dot shows session recency: green (<5 min), yellow (5-10 min), orange (10-20 min).
- **Resume Commands** — Copy-pasteable per-provider resume command (`claude --resume <id>`, `codex --resume <id>`, `opencode -s <id>`) on every session, with one-click clipboard copy.
- **Session Titles** — Shows AI-generated or user-set session names alongside session IDs.
- **Token & Cost Summary** — Per-session and per-turn token breakdowns with cost estimates for known models.
- **Live Updates** — Polls for changes and auto-refreshes the view, including during active sessions.

## Supported Providers

| Provider | Sessions stored in | Notes |
|----------|-------------------|-------|
| Claude Code | `~/.claude/projects/<project-slug>/<session-id>.jsonl` | One JSONL file per session; also provides prompt history (`~/.claude/history.jsonl`) and project memories |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` | One JSONL file per session, grouped by date; projects inferred from the session's working directory |
| OpenCode | `~/.local/share/opencode/opencode.db` | Single SQLite database holding all sessions (`session`/`message`/`part` tables); read in read-only mode so a running opencode is undisturbed. Multiple databases can be configured (see Configuration) |

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone and install
git clone git@github.com:tyraziel/agent-session-viewer.git
cd agent-session-viewer
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
  --claude-dir DIR   Path to Claude config directory (default: ~/.claude or CLAUDE_CONFIG_DIR)
  --config CONFIG    Path to config file (default: ~/.config/claude-project-viewer/config.json)
```

## Configuration

No config file is required — every provider uses its default location. To
enable/disable a provider or add extra session locations, create
`~/.config/claude-project-viewer/config.json`:

```json
{
  "providers": {
    "claude": {
      "enabled": true,
      "session_paths": ["/extra/path/to/projects"],
      "include_default": true
    },
    "codex": {
      "enabled": true,
      "include_default": true
    },
    "opencode": {
      "enabled": true,
      "session_paths": ["/backups/opencode.db", "/synced-dbs/"],
      "include_default": true
    }
  }
}
```

- `enabled` — set `false` to hide a provider entirely.
- `session_paths` — extra locations to scan. For OpenCode, entries may be a
  `.db` file or a directory (any file in it that looks like an OpenCode
  database is used; others are skipped).
- `include_default` — also scan the provider's default location (default `true`).

## How It Works

Each provider implements a common interface: discover projects, parse a
session into a shared model, read a session tail for active-session cards, and
look up per-model pricing. The UI operates on the shared model, so a session
from any provider renders identically.

- **Claude Code** stores transcripts as JSONL in
  `~/.claude/projects/<project-slug>/<session-id>.jsonl`, where
  `<project-slug>` is the working directory with non-alphanumeric characters
  replaced by dashes. Each line is a JSON message, tool call, or metadata
  entry; tool results masquerading as user messages are identified and
  separated from real human input, and mid-turn messages (sent while Claude is
  working) are captured from `queue-operation` entries.
- **Codex CLI** stores transcripts as JSONL rollout files organized by date;
  turns are delimited by `task_started` events and token usage arrives via
  `token_count` events.
- **OpenCode** keeps everything in one SQLite database; the provider opens it
  read-only, joins `message` and `part` rows, and maps content part types
  (text, reasoning, tool) onto the shared model.

## Project Structure

```
src/claude_project_viewer/
├── __main__.py          # CLI entry point, provider registration
├── app.py               # NiceGUI routes, shared in-memory UI state
├── config.py            # Config file loading, per-provider path resolution
├── discovery.py         # Cross-provider project/session discovery
├── formatting.py        # Display helpers (time ago, file size, activity)
├── parser.py            # Shared session model + Claude JSONL parser
├── pricing.py           # Claude model pricing
└── pages/
    ├── breadcrumbs.py   # Shared breadcrumb navigation
    ├── history.py       # Prompt history page (Claude)
    ├── memory.py        # Project memory viewer (Claude)
    ├── projects.py      # Project listing across all providers
    ├── session_detail.py # Turn-by-turn session viewer
    └── session_list.py  # Session listing for a project

src/claude_project_viewer/providers/
├── __init__.py      # ProviderBase interface + registry
├── claude.py        # Claude Code provider
├── codex.py         # Codex CLI provider
└── opencode.py      # OpenCode provider (SQLite)
```

## Cost Estimation Disclaimer

Token cost estimates displayed in the session viewer are based on published
list prices as of August 20th, 2026 — [Anthropic](https://www.anthropic.com/pricing)
for Claude models and [OpenAI](https://openai.com/api/pricing/) for GPT
models. Actual costs may differ due to negotiated rates, billing tier, proxy
or gateway providers, or pricing changes. These figures are approximate and
should not be used for accounting purposes. Sessions using models without
known pricing (e.g. local or custom models) show no cost estimate.

## AI Attribution

[AIA PAI SeCeNc Hin R Claude Code [Opus 4.6 1m], opencode [Qwen3-8-27B] v1.0](https://aiattribution.github.io/statements/AIA-PAI-SeCeNc-Hin-R-?model=Claude%20Code%20%5BOpus%204.6%201m%5D%2C%20opencode%20%5BQwen3-8-27B%5D-v1.0)

This work was primarily AI-generated. AI was used to make stylistic edits, such as changes to structure, wording, and clarity. AI was used to make content edits, such as changes to scope, information, and ideas. AI was used to make new content, such as text, images, analysis, and ideas. AI was prompted for its contributions, or AI assistance was enabled. AI-generated content was reviewed and approved. The following model(s) or application(s) were used: Claude Code [Opus 4.6 1m], opencode [Qwen3-8-27B].

## License

See [LICENSE](LICENSE).
