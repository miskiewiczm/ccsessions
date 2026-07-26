# ccsessions

A fast terminal UI for browsing, previewing, resuming and managing
[Claude Code](https://claude.com/claude-code) sessions.

<!-- TODO: add a screenshot or GIF here, e.g.:
![ccsessions demo](docs/demo.gif)
Record one with https://github.com/charmbracelet/vhs -->

## Features

- **Project & session browser** — every Claude Code project on your machine,
  newest first, with live-session indicators (●), message counts and token
  usage (input / output / cache read / cache write)
- **Conversation preview** — the tail of any session rendered with roles,
  Markdown (for Claude's replies), tool calls (⚙) and slash commands (⌘),
  without opening Claude Code
- **One-key resume** — `r` replaces the TUI with `claude --resume <id>` in the
  session's working directory; `c` copies a ready
  `cd <dir> && claude --resume <id>` command to the clipboard (OSC 52)
- **Archive & delete** — move sessions out of `claude --resume` (reversibly)
  or delete them for good, per session or per project, with confirmation
  dialogs; sessions whose transcript lives on another synced machine are
  detected and marked (✕)
- **Responsive layout** — wide terminals get a side-by-side layout with a
  full-height conversation pane; narrow (half-screen) terminals get a stacked
  layout with a full-width conversation pane
- **Fast** — token stats are cached per transcript (invalidated by
  mtime + size), scanning runs off the UI thread, and conversation previews
  read only the tail of multi-megabyte files

## Requirements

- Python ≥ 3.10
- [Claude Code](https://claude.com/claude-code) installed (`claude` on PATH —
  needed only for resuming)
- macOS or Linux (Windows untested)

## Installation

```bash
pipx install ccsessions        # or: uv tool install ccsessions
```

Or from a clone:

```bash
git clone https://github.com/CHANGE-ME/ccsessions
pip install -e ccsessions
```

## Usage

```bash
ccsessions
```

| Key | Action |
| --- | --- |
| `j` / `k` / arrows | Move within the focused pane |
| `Tab` / `Shift+Tab` | Switch panes |
| `r` | Resume the selected session (in place) |
| `c` | Copy the resume command to the clipboard |
| `a` | Archive ↔ restore session · archive project |
| `d` | Delete session / project (with confirmation) |
| `Ctrl+R` | Rescan `~/.claude` |
| `q` | Quit |

`a` and `d` act on the **session** when the Sessions pane is focused and on
the whole **project** when the Projects pane is focused.

### Configuration

- `CCSESSIONS_CODE_THEME` — pygments theme for code blocks in the
  conversation pane (default: `nord`). Any name from
  `pygments.styles.get_all_styles()` works, e.g. `monokai`, `dracula`,
  `github-dark`, `one-dark`, `gruvbox-dark`.

## How it works

ccsessions reads the data Claude Code already keeps on disk:

- `~/.claude/projects/<encoded-path>/*.jsonl` — session transcripts
- `~/.claude/projects/<encoded-path>/sessions-index.json` — session metadata
  (summaries, first prompts, message counts)
- `~/.claude/sessions/*.json` — live-session records (PID liveness is checked
  with signal 0)

Archiving a session moves its transcript into an `archived/` subdirectory of
the project folder (invisible to `claude --resume`, fully restorable).
Archiving a project moves the whole folder to `~/.claude/projects-archive/`.
Deleting removes the transcript and its index entry. Token-stats caching
lives in `~/.cache/ccsessions/`.

> **Note:** Claude Code automatically deletes transcripts older than its
> `cleanupPeriodDays` setting (30 days by default). If you rely on your
> session history, raise that value in `~/.claude/settings.json`.

## Privacy

Everything happens locally: ccsessions only reads files under `~/.claude/`
and writes its cache under `~/.cache/ccsessions/`. It makes no network
requests and sends nothing anywhere.

## Development

```bash
pip install -e . --group dev
pytest
```

## License

[MIT](LICENSE)
