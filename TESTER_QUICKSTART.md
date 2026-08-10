# Apsara Agentic: Tester Quickstart 🚀

Welcome to the Apsara alpha test! Follow these steps to get the AI coding agent running in your local workspace.

## 1. Installation

Ensure you have **Python 3.10–3.14**, **pipx**, and **Git** installed.

```bash
# Install the exact private-alpha build
pipx install https://github.com/RithyBondeth/Apsara-Agentic-Cli/releases/download/v0.1.0a1/apsara_agentic-0.1.0a1-py3-none-any.whl
```

For source development instead, follow
[RUN_PROJECT.md](https://github.com/RithyBondeth/Apsara-Agentic-Cli/blob/main/RUN_PROJECT.md).

## 2. Start Apsara

Apsara is **bring-your-own-key**: you pick a model provider and use your own API
key. Apsara never sends your key to any Apsara server—it is stored locally only
if you approve saving it.

```bash
cd /path/to/your/work/project
apsara
```

The full-screen UI opens immediately with OpenCode Zen's Big Pickle model. Send
your first request; if the OpenCode key is missing, Apsara requests it inline
with hidden input. Choose whether to keep it for the session or store it in
`~/.apsara/credentials.json` (owner-only, `chmod 600`). Use `/models` to choose
another provider or local Ollama.

Run `apsara logout` at any time to clear all stored keys.

### Alternative: environment variables

You can also export the provider's key yourself (or put it in a project
`.env`). An explicitly-set environment variable always takes
precedence over a stored key:

```bash
export OPENCODE_API_KEY="your-key"  # or OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

For safety, project `.env` files load provider credential keys only. Export
advanced runtime settings in your shell; a checked-out project cannot use its
`.env` to redirect the API or raise Apsara's token budget.

Big Pickle is free for a limited period. OpenCode states that submitted data
may be used to improve the model during that period, so do not test it with
confidential repositories.

Run `apsara doctor` to confirm your provider and key are detected.

## 3. Optional: Initialize your Project

Go to the project you want to work on and initialize Apsara.

```bash
cd /path/to/your/work/project
apsara init
```

This will:
- Create `.apsara/config.toml` for your local settings.
- Create `.apsara/instructions.md` for **Team Standards** (edit this to tell the agent how you like your code formatted).
- Update your `.gitignore` to keep Apsara logs and sessions private.

Initialization is optional; bare `apsara` works directly in any project.

## 4. Start Chatting

```bash
apsara
```

### Useful Slash Commands:
- `/help` - Show all commands.
- `/add <path>` - Pin a file to the context.
- `/status` - Check token usage and session cost.
- `/bug` - Save a privacy-safe diagnostic bundle with conversation and source
  content omitted by default.
- `/bug --include-content` - Include redacted conversation and tool content
  after an explicit confirmation when a reproduction needs it.
- `/details` - See hidden tool and planning activity.

## 5. Safety Tips
- Apsara asks before workspace file mutations by default. Shell commands,
  background processes, project-supplied code, and external mutations always
  require explicit approval, even with `--auto-approve`.
- Use `apsara --dry-run` to see what it *would* do without touching your files.
- Use `apsara --read-only` if you just want it to explain the code.

---
**Happy Coding!** If you encounter unusual behavior, run `/bug`, open the newly
created bundle under `.apsara/bugs/`, and review every file before sharing that
specific bundle. Do not share the entire `.apsara/bugs/` directory blindly.
