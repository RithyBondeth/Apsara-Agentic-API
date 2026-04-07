# Apsara by Bondeth Tester Quickstart

This is the shortest path for an alpha tester to try Apsara locally.

## 1. Open the project

```bash
cd "/Users/bondeth/Projects/Apsara Agentic/apsara-agentic-api"
```

## 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

## 4. Add your OpenAI API key to `.env`

```env
OPENAI_API_KEY=your_openai_api_key
```

## 5. Run the CLI health check

```bash
python3 -m app.cli doctor --workspace .
```

## 6. Start Apsara

```bash
python3 -m app.cli init --workspace . --model gpt-5.4-mini
```

If the `apsara` command is installed, testers can also use:

```bash
apsara init
```

## 7. Try these prompts

Prompt 1:

```text
Describe this project.
```

Prompt 2:

```text
Find the main CLI file and summarize what it does.
```

Prompt 3:

```text
Suggest one small improvement to the CLI UI and implement it.
```

## 8. Test the edit review flow

When Apsara proposes a code change:
- `Enter` approves
- `n` rejects
- `a` approves the rest of the session
- `v` shows a fuller diff in the terminal
- `e` opens the patch in your editor

## 9. Useful chat commands

```text
/details
/clear
```

## 10. If something goes wrong

Please send:
- the command you ran
- the prompt you asked
- the full error message
- a screenshot or terminal copy if possible

## 11. More detailed docs

- Alpha release notes: [RELEASE_NOTES_ALPHA.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/RELEASE_NOTES_ALPHA.md)
- Alpha testing guide: [ALPHA_TESTING.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/ALPHA_TESTING.md)
- Run guide: [RUN_PROJECT.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/RUN_PROJECT.md)
- Main README: [README.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/README.md)
