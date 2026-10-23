# Agent Session Viewer

A pure Python web UI for browsing sessions, project memories, and prompt history from AI coding agent CLIs. Built with [NiceGUI](https://nicegui.io/).

Supports **Claude Code**, **Codex CLI**, **OpenCode**, and **Pi** out of the box, with a provider abstraction for adding more.

Web UI patterns adopted from [ai-guardian's](https://github.com/RedHatProductSecurity/ai-guardian) trace viewer.

## Features

- **Project Browser** — Lists all projects across every enabled provider with session counts, sizes, last-activity times, and provider badges. Auto-refreshes when sessions change on disk.
- **Session Viewer** — Turn-by-turn conversation viewer with inline recap (your prompt + the agent's response) and expandable full details showing all tool calls, results, thinking blocks, and system messages.
- **Multi-Provider** — Claude Code, Codex CLI, OpenCode, and Pi sessions are discovered, parsed, and rendered through a shared provider abstraction; each provider keeps its own storage format, resume commands, and pricing.
- **Prompt History** — Browse `~/.claude/history.jsonl` with filtering by project and text search. Entries with session IDs link directly to the session viewer.
- **Memory Viewer** — Browse Claude project-level memories grouped by type (user, feedback, project, reference) with YAML frontmatter parsing.
- **Activity Indicators** — Pulsing colored dot shows session recency: green (<5 min), yellow (5-10 min), orange (10-20 min).
- **Resume Commands** — Copy-pasteable per-provider resume command (`claude --resume <id>`, `codex --resume <id>`, `opencode -s <id>`, `pi --session <id>`) on every session, with one-click clipboard copy.
- **Session Titles** — Shows AI-generated or user-set session names alongside session IDs.
- **Token & Cost Summary** — Per-session and per-turn token breakdowns with cost estimates for known models.
- **Live Updates** — Polls for changes and auto-refreshes the view, including during active sessions.

## Supported Providers

| Provider | Sessions stored in | Notes |
|----------|-------------------|-------|
| Claude Code | `~/.claude/projects/<project-slug>/<session-id>.jsonl` | One JSONL file per session; also provides prompt history (`~/.claude/history.jsonl`) and project memories |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` | One JSONL file per session, grouped by date; projects inferred from the session's working directory. Optional per-thread summaries and memory are read from `~/.codex/memories_*.sqlite` |
| OpenCode | `~/.local/share/opencode/opencode.db`; exported `*ses_*.json` files | Reads the live SQLite database and exported JSON sessions through the same OpenCode provider; session paths can include multiple databases, export files, or directories containing them |
| Pi | `~/.pi/agent/sessions/--<encoded-project-path>--/<timestamp>_<session-id>.jsonl` | One JSONL file per session, grouped by working directory; entries form a tree and the viewer follows the active branch |

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone and install
git clone https://github.com/tyraziel/agent-session-viewer.git
cd agent-session-viewer
uv sync

# Run
uv run agent-session-viewer
```

The agent-session-viewer will run on port 8090.

## CLI Options

```
uv run agent-session-viewer [OPTIONS]

Options:
  --port PORT        Port to serve on (default: 8090)
  --host HOST        Host to bind to (default: 127.0.0.1)
  --claude-dir DIR   Path to Claude config directory (default: ~/.claude or CLAUDE_CONFIG_DIR)
  --config CONFIG    Path to config file (default: ~/.config/agent-session-viewer/config.json)
```

## Configuration

No config file is required — every provider uses its default location. To
enable/disable a provider or add extra session locations, create
`~/.config/agent-session-viewer/config.json`:

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
      "session_paths": [
        {
          "path": "/codex/artifact-root",
          "recursive": true,
          "deduplicate": true
        }
      ],
      "include_default": true,
      "memory_paths": ["/backup/codex/memories.sqlite"],
      "include_default_memory": true
    },
    "opencode": {
      "enabled": true,
      "session_paths": [
        "/backups/opencode.db",
        {
          "path": "/synced-dbs",
          "recursive": true,
          "deduplicate": true
        },
        {
          "path": "/exports/opencode",
          "recursive": true,
          "deduplicate": true
        }
      ],
      "include_default": true
    },
    "pi": {
      "enabled": true,
      "session_paths": ["/extra/path/to/pi/sessions"],
      "include_default": true
    }
  }
}
```

- `enabled` — set `false` to hide a provider entirely.
- `session_paths` — extra locations to scan. Entries may remain strings to
  preserve the provider's existing scan behavior, or be objects with a required
  `path` and optional `recursive` flag. For objects, `recursive` defaults to
  `false`; set it to `true` to descend through nested directories. OpenCode
  paths may point to `.db` files, exported JSON files, or directories containing
  SQLite databases and `*ses_*.json` exports.
- Path objects also accept `deduplicate` (default `false`) to skip identical
  file contents found within that path's scan.
- `include_default` — also scan the provider's default location (default `true`).
- `memory_paths` — Codex-only memory databases to check for a matching thread.
  Entries may be database files, directories containing `memories_*.sqlite`,
  or filename globs. Multiple locations can be configured.
- `include_default_memory` — for Codex, also check
  `~/.codex/memories_*.sqlite` (default `true`). Set it to `false` to use only
  `memory_paths`. The session summary card is hidden when no matching,
  non-empty record exists. Memory records are keyed by thread ID and may also
  originate from ChatGPT UI sessions.

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
- **OpenCode** stores live sessions in SQLite and can also export individual
  sessions as JSON. The provider reads SQLite databases in read-only mode or
  parses exported JSON files, mapping text, reasoning, and tool parts onto the
  shared model.
- **Pi** stores sessions as JSONL files grouped by an encoded working-directory
  folder. Entries form a parent-linked tree; the provider follows the current
  branch and maps messages, tool calls/results, usage, and summaries into the
  shared model. See [Pi Session Format](docs/pi_session_format.md).

For the provider contracts, current storage formats, and end-to-end steps for
adding another provider, see [Provider Architecture](docs/provider_architecture.md)
and [Adding a Provider](docs/adding_a_provider.md). Pi is from
[pi.dev](https://pi.dev/) ([source repository](https://github.com/earendil-works/pi)).

## Project Structure

```
src/agent_session_viewer/
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

src/agent_session_viewer/providers/
├── __init__.py      # ProviderBase interface + registry
├── claude.py        # Claude Code provider
├── codex.py         # Codex CLI provider
├── opencode.py      # OpenCode provider (SQLite + JSON exports)
└── pi.py            # Pi provider (JSONL session trees)
```

## Cost Estimation Disclaimer

Token cost estimates displayed in the session viewer use published standard
API text-token list prices checked on September 24, 2026 —
[Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) for Claude
models and [OpenAI](https://developers.openai.com/api/docs/pricing) for OpenAI
models.

OpenAI long-context rates and Anthropic's cache-write TTL rates are applied
when the session usage data provides the necessary detail. OpenAI context-tier
selection is inferred from input and cache token counts in the session logs,
so it may differ from the provider's context accounting.

Actual spend may be higher or lower due to negotiated rates, billing tier, proxy
or gateway providers, service tier, modality-specific charges, or pricing
changes. These estimates should not be used for accounting purposes. Sessions
using models without known pricing (e.g. local or custom models) show no cost
estimate.

## AI Attribution

[AIA PAI SeCeNc Hin R Claude Code [Opus 4.6 1m], opencode [Qwen3-8-27B], opencode [gpt-6-luna high] v1.0](https://aiattribution.github.io/statements/AIA-PAI-SeCeNc-Hin-R-?model=Claude%20Code%20%5BOpus%204.6%201m%5D%2C%20opencode%20%5BQwen3-8-27B%5D%2C%20opencode%20%5Bgpt-6-luna%20high%5D-v1.0)

This work was primarily AI-generated. AI was used to make stylistic edits, such as changes to structure, wording, and clarity. AI was used to make content edits, such as changes to scope, information, and ideas. AI was used to make new content, such as text, images, analysis, and ideas. AI was prompted for its contributions, or AI assistance was enabled. AI-generated content was reviewed and approved. The following model(s) or application(s) were used: Claude Code [Opus 4.6 1m], opencode [Qwen3-8-27B], opencode [gpt-6-luna high].

## License

See [LICENSE](LICENSE).
