# Apsara Agentic

A local, bring-your-own-key coding agent for your terminal. Apsara reads and
edits code in a workspace you choose, runs allowlisted commands, and connects to
external tools over MCP — using your own API key, with no Apsara server in the
middle.

> **Alpha.** The CLI is usable day to day, but interfaces may still change
> between releases.

## Requirements

- Python 3.10 or newer
- `git` on your PATH (for the `git_status` / `git_diff` tools)
- An API key from a model provider, or a local Ollama install

## Install

```bash
pipx install apsara-agentic
```

Or, if you'd rather install through npm (it wraps the same Python package):

```bash
npm install -g apsara-cli
```

## Quickstart

```bash
apsara login
```

Pick a provider (OpenAI, Anthropic, Google, Groq, Mistral, DeepSeek, or local
Ollama) and paste your own API key. It's verified immediately and stored in
`~/.apsara/credentials.json` with owner-only permissions. Nothing is sent to an
Apsara server — there isn't one.

```bash
cd /path/to/your/project
apsara init
```

That creates `.apsara/config.toml`, adds Apsara's local artifacts to
`.gitignore`, and opens chat in the current project. After that:

```bash
apsara chat
```

## Commands

| Command | What it does |
| --- | --- |
| `apsara chat` | Interactive session in the current workspace |
| `apsara run "<instruction>"` | One-shot instruction, then exit |
| `apsara init` | Set up `.apsara/` in this project and start chatting |
| `apsara sessions` | List saved sessions for a workspace |
| `apsara mcp` | List configured MCP servers and verify they connect |
| `apsara doctor` | Check environment, config, tools, and credentials |
| `apsara login` / `logout` | Manage stored provider keys |
| `apsara --version` | Print the installed version |

Run `apsara <command> --help` for the full flag list.

## Tools

The agent works through a workspace-scoped tool sandbox. Every path is resolved
inside the workspace root; attempts to escape it fail.

**Reading** — `read_file`, `read_file_lines`, `glob_search`, `search_files`,
`list_project_structure`, `list_symbols` (Python), `git_status`, `git_diff`

**Writing** — `edit_file`, `replace_file_lines`, `write_to_file`,
`create_directory`, `move_file`, `delete_file`

**Commands** — `run_bash_command`, off by default; see below.

`edit_file` is the primary editing tool: it replaces an exact snippet of text
and refuses ambiguous or missing matches, so an edit can't silently land in the
wrong place after earlier changes shift the file. `replace_file_lines` still
exists for the rare case with no unique text to match on.

Every write shows a diff preview and asks for approval. In the prompt, `Enter`
approves, `n` rejects, `a` approves the rest of the session, `v` shows the full
patch, and `e` opens it in `$EDITOR`.

### Command execution

The bash tool is disabled by default. Enable it with an explicit allowlist:

```bash
apsara chat --allow-bash --allowed-commands pytest,npm,git,rg
```

Commands are parsed and checked against the allowlist — including every stage of
a pipe or `&&` chain — and redirections that would write outside the workspace
are rejected.

## MCP servers

Apsara is an MCP client, so it can use any Model Context Protocol server:
filesystem, git, GitHub, databases, browser automation, or your own internal
tools. Declare servers in `.apsara/config.toml`:

```toml
# Launched as a subprocess over stdio
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "."]

# Reached over streamable HTTP
[mcp_servers.internal]
url = "https://mcp.example.com/v1"
headers = { Authorization = "Bearer ${MCP_TOKEN}" }
timeout = 30
```

`$VAR` and `${VAR}` are expanded from the environment, so tokens stay out of the
config file. Set `enabled = false` to keep a server defined but switched off.

Their tools appear to the agent as `mcp__<server>__<tool>` and cannot collide
with the built-ins. Servers connect once per session, and a server that fails to
start is reported and skipped rather than taking the session down.

Check your setup any time:

```bash
apsara mcp
```

## Trust

Two things can arrive with a repository rather than from you: local plugins in
`.apsara/tools/*.py` and MCP server definitions in `.apsara/config.toml`. Both
execute code, so Apsara asks before running either one, showing what it's about
to execute. Approvals are recorded per project in `~/.apsara/trust.json`, keyed
by a digest of the code — if an approved file changes, you're asked again.

`--auto-approve` does **not** cover this. That flag waives confirmation for file
writes; it is not consent to execute a project's code.

## Configuration

Settings resolve in this order: CLI flags → project `.apsara/config.toml` →
global `~/.apsara/config.toml` → `.env`.

```toml
[defaults]
workspace = "."
model = "gpt-4o"
session = "default"
stateless = false
allow_bash = false
allowed_commands = ["pytest", "rg"]
max_file_size = 1000000
auto_approve = false
color = true

[ui]
welcome_title = "Welcome to Apsara Agentic"
welcome_subtitle = "A focused terminal coding assistant"
welcome_animation = true
```

Useful flags:

- `--workspace <path>` — the directory the agent may access
- `--model <name>` — any model LiteLLM can route to
- `--read-only` — disable every destructive tool
- `--dry-run` — preview changes without touching disk
- `--auto-approve` — skip write confirmations
- `--stateless` — don't load or save session history
- `--config <path>` — use a specific config file

## Sessions

Conversations are saved as JSON under `.apsara-cli/sessions/` in the workspace —
local files, no database. Long conversations are summarized and trimmed
automatically to stay within the model's context budget, while the full history
stays on disk.

In chat, slash commands include `/help`, `/details`, `/history`, `/tools`,
`/model`, `/session`, `/add <path>`, `/save`, and `/bug`.

## Extending with local plugins

Drop a Python file in `.apsara/tools/` that exports `METADATA` and `run()`:

```python
METADATA = {
    "name": "ticket_lookup",
    "description": "Fetch a ticket summary by id.",
    "parameters": {
        "type": "object",
        "properties": {"ticket_id": {"type": "string"}},
        "required": ["ticket_id"],
    },
}

def run(ticket_id: str) -> str:
    return f"Ticket {ticket_id}: ..."
```

You'll be asked to approve it the first time it loads. For anything you'd want
to share across projects or teams, prefer an MCP server.

## Development

```bash
git clone https://github.com/RithyBondeth/Apsara-Agentic-Cli.git
cd Apsara-Agentic-Cli
python -m pip install -e ".[dev]"
python -m pytest
```

Local run notes are in
[RUN_PROJECT.md](https://github.com/RithyBondeth/Apsara-Agentic-Cli/blob/main/RUN_PROJECT.md),
and tester setup is in
[TESTER_QUICKSTART.md](https://github.com/RithyBondeth/Apsara-Agentic-Cli/blob/main/TESTER_QUICKSTART.md).
Maintainers: see `RELEASING.md` in the repository for the publish process.

## License

MIT — see [LICENSE](https://github.com/RithyBondeth/Apsara-Agentic-Cli/blob/main/LICENSE).
