# How To Run Apsara Agentic

This guide shows how to run the project step by step.

## 1. Go to the project folder

```bash
cd "/Users/bondeth/Projects/Apsara Agentic/apsara-agentic-api"
```

## 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If you already created `.venv`, just run:

```bash
source .venv/bin/activate
```

## 3. Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

Optional: install the CLI command:

```bash
python3 -m pip install -e .
```

If `pip install -e .` fails because of old packaging tools, upgrade them first:

```bash
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e .
```

If you still do not have the `apsara` command, you can always use:

```bash
python3 -m app.cli
```

## 4. Configure the environment

Edit `.env` in the project root:

```env
PROJECT_NAME=Apsara Agentic API
API_V1_STR=/api/v1
DEBUG=true
SQLALCHEMY_DATABASE_URI=postgresql://user:password@localhost:5432/dbname
OPENAI_API_KEY=your_openai_api_key
AGENT_WORKSPACE_ROOT=.
AGENT_ENABLE_BASH_TOOL=false
AGENT_ALLOWED_COMMANDS=pwd,ls,find,rg,cat,sed,head,tail,wc
AGENT_MAX_FILE_SIZE_BYTES=1000000
```

Important:
- `OPENAI_API_KEY` is required for the CLI and agent model calls.
- The CLI now auto-loads `.env`, so you do not need to export the key manually.
- `SQLALCHEMY_DATABASE_URI` is required for the API server and database-backed routes.

## 5. Run the local CLI first

This is the easiest way to confirm the project works.

Recommended project-first flow:

```bash
cd /path/to/your/project
apsara init
```

That initializes the folder and starts chat immediately. If `apsara` is not installed yet, keep using the module form below.

Run the doctor command:

```bash
python3 -m app.cli doctor --workspace .
```

Or, if `apsara` is installed:

```bash
apsara doctor --workspace .
```

If you want a real live model check, run:

```bash
python3 -m app.cli doctor --workspace . --model gpt-5.4-mini --live
```

Start the interactive coding assistant:

```bash
python3 -m app.cli chat --workspace . --model gpt-5.4-mini
```

Or:

```bash
apsara chat --workspace . --model gpt-5.4-mini
```

Once a project has been initialized, you can usually just do:

```bash
apsara chat
```

Run a one-shot prompt:

```bash
python3 -m app.cli run "Describe this project" --workspace . --model gpt-5.4-mini
```

## 6. Run the FastAPI server

Make sure PostgreSQL is running and the database in `.env` exists.

Apply migrations:

```bash
alembic upgrade head
```

Start the API server:

```bash
python3 -m uvicorn app.main:app --reload
```

Or use the helper script:

```bash
./run-dev.sh
```

## 7. Open the app endpoints

After the server starts, open:

- Root: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- Health: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)
- Swagger Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## 8. If the CLI shows `quota exceeded`

That usually means:

- your API key is being read correctly
- but the OpenAI API account does not have available billing or credits

Fix:

1. Add billing or prepaid credits to your OpenAI API account.
2. Confirm the key belongs to the correct API project.
3. Retry:

```bash
python3 -m app.cli doctor --workspace . --model gpt-5.4-mini --live
python3 -m app.cli chat --workspace . --model gpt-5.4-mini
```

## 9. Recommended first run order

Use this order if you want the smoothest setup:

1. Activate `.venv`
2. Install dependencies
3. Add `OPENAI_API_KEY` to `.env`
4. Run `python3 -m app.cli doctor --workspace .`
5. Run `python3 -m app.cli chat --workspace . --model gpt-5.4-mini`
6. Start PostgreSQL
7. Run `alembic upgrade head`
8. Run `python3 -m uvicorn app.main:app --reload`

## 10. Files you may want to check

- Project guide: [README.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/README.md)
- CLI entrypoint: [app/cli.py](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/app/cli.py)
- App config: [app/core/config.py](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/app/core/config.py)
- Development runner: [run-dev.sh](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/run-dev.sh)
