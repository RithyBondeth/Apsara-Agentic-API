# Apsara Agentic API

A FastAPI backend for running project-scoped agent conversations with PostgreSQL-backed conversation history and usage tracking.

## Current Features

- Health check endpoint with database validation
- Agent execution endpoint with Server-Sent Events streaming
- Conversation and message persistence in PostgreSQL
- Local CLI for workspace-scoped coding assistance and saved sessions
- LiteLLM-based model selection with tool calling
- Workspace-scoped file tools for reading, writing, searching, listing, and line replacement
- Token usage logging for each model call

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   To install the local CLI as an `apsara` command in your active Python environment:

   ```bash
   pip install -e .
   ```

2. Configure `.env`:

   ```env
   PROJECT_NAME=Apsara Agentic API
   API_V1_STR=/api/v1
   DEBUG=true
   SQLALCHEMY_DATABASE_URI=postgresql://user:password@localhost:5432/dbname
   AGENT_WORKSPACE_ROOT=.
   AGENT_ENABLE_BASH_TOOL=false
   AGENT_ALLOWED_COMMANDS=pwd,ls,find,rg,cat,sed,head,tail,wc
   AGENT_MAX_FILE_SIZE_BYTES=1000000
   ```

3. Run the application:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Open the API docs:

   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Authentication

Protected agent routes require an `X-User-Id` header containing the UUID of an existing user in the database.

## Local CLI

The project includes a local CLI that runs the agent directly against a workspace on your machine.

Optional global config file:

```toml
# ~/.apsara/config.toml
[defaults]
workspace = "/absolute/path/to/your/project"
model = "gpt-4o"
session = "default"
stateless = false
allow_bash = false
allowed_commands = ["pwd", "rg", "pytest"]
max_file_size = 1000000
auto_approve = false
color = true

[ui]
welcome_title = "Welcome to Apsara Agentic"
welcome_subtitle = "A focused terminal coding assistant"
powered_by = "Powered by Bondeth"
welcome_animation = true
welcome_frame_delay_ms = 22
```

Run one instruction:

```bash
apsara run "Summarize this codebase" --workspace /path/to/project
```

Open an interactive session:

```bash
apsara chat --workspace /path/to/project --session main
```

List saved sessions for a workspace:

```bash
apsara sessions --workspace /path/to/project
```

Run an environment readiness check:

```bash
apsara doctor --workspace /path/to/project --model gpt-4o
```

If you want the doctor command to attempt a real model call after the offline checks pass:

```bash
apsara doctor --workspace /path/to/project --model gpt-4o --live
```

Useful flags:

- `--config /path/to/config.toml` to override the default global config path
- `--allow-bash --allowed-commands pwd,rg,pytest` to opt into local non-interactive command execution
- `--auto-approve` to skip confirmation prompts for writes and commands
- `--no-color` to disable colored terminal output

By default, the CLI saves session history under `.apsara-cli/sessions/` inside the workspace. Use `--stateless` to disable that. In chat mode, slash commands like `/help`, `/history`, `/tools`, `/model`, `/session`, and `/save` are available. File writes, line replacements, and local commands ask for confirmation unless you explicitly use `--auto-approve`. The `doctor` command checks Python support, config loading, workspace access, session storage writability, tool availability, likely credential env vars for the selected model, and optionally a real live model probe.

The CLI automatically loads `.env` files from the workspace root and the current working directory before it runs. Explicitly exported shell variables still take precedence.

The chat welcome banner is customizable through the `[ui]` section of the config file. Animation is enabled by default for interactive terminals and automatically turns off in CI or non-interactive sessions.

## API Surface

- `GET /`
- `GET /api/v1/health`
- `POST /api/v1/agent/{conversation_id}/run`

## Project Structure

```text
app/
├── api/
│   └── v1/
│       ├── api.py
│       └── endpoints/
│           ├── agent.py
│           └── health.py
├── core/
│   └── config.py
├── db/
│   ├── base.py
│   ├── base_class.py
│   └── session.py
├── models/
├── schemas/
└── services/
    └── agent/
alembic/
.env
requirements.txt
```
