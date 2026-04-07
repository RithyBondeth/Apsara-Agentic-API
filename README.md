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

Run one instruction:

```bash
python3 -m app.cli run "Summarize this codebase" --workspace /path/to/project
```

Open an interactive session:

```bash
python3 -m app.cli chat --workspace /path/to/project --session main
```

List saved sessions for a workspace:

```bash
python3 -m app.cli sessions --workspace /path/to/project
```

By default, the CLI saves session history under `.apsara-cli/sessions/` inside the workspace. Use `--stateless` to disable that. Use `--allow-bash` plus `--allowed-commands` if you want to opt into local non-interactive command execution for the CLI.

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
