# Apsara Agentic: Tester Quickstart 🚀

Welcome to the Apsara alpha test! Follow these steps to get the AI coding agent running in your local workspace.

## 1. Installation

Ensure you have **Python 3.9+** and **Git** installed.

```bash
# Clone the repository (if you haven't)
git clone https://github.com/your-repo/apsara-agentic.git
cd apsara-agentic/apsara-agentic-cli

# Install the package in editable mode
pip install -e .
```

## 2. Choose a Provider & Add Your API Key

Apsara is **bring-your-own-key**: you pick a model provider and use your own API
key. Apsara never sends your key to any Apsara server — it's stored locally.

```bash
# Pick a provider and paste your key
apsara login
```

You'll get a menu of providers (OpenCode Zen, OpenAI, Anthropic, Google, Groq,
Mistral, DeepSeek, and local Ollama). OpenCode Zen with Big Pickle is the
default. Choose one, paste that provider's API key when
prompted (input is hidden), and Apsara verifies it and stores it securely in
`~/.apsara/credentials.json` (owner-only, `chmod 600`). Ollama is local and
needs no key.

Run `apsara logout` at any time to clear all stored keys.

### Alternative: environment variables

Instead of `apsara login`, you can export the provider's key yourself (or put it
in a project `.env`). An explicitly-set environment variable always takes
precedence over a stored key:

```bash
export OPENCODE_API_KEY="your-key"  # or OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

Big Pickle is free for a limited period. OpenCode states that submitted data
may be used to improve the model during that period, so do not test it with
confidential repositories.

Run `apsara doctor` to confirm your provider and key are detected.

## 3. Initialize your Project

Go to the project you want to work on and initialize Apsara.

```bash
cd /path/to/your/work/project
apsara init
```

This will:
- Create `.apsara/config.toml` for your local settings.
- Create `.apsara/instructions.md` for **Team Standards** (edit this to tell the agent how you like your code formatted).
- Update your `.gitignore` to keep Apsara logs and sessions private.

## 4. Start Chatting

```bash
apsara chat
```

### Useful Slash Commands:
- `/help` - Show all commands.
- `/add <path>` - Pin a file to the context.
- `/status` - Check token usage and session cost.
- `/bug` - If the agent gets stuck, run this to save diagnostic logs.
- `/details` - See the agent's hidden thought process.

## 5. Safety Tips
- Apsara will **always ask for confirmation** before writing files or running commands.
- Use `apsara chat --dry-run` to see what it *would* do without touching your files.
- Use `apsara chat --read-only` if you just want it to explain the code.

---
**Happy Coding!** Please share your `.apsara/bugs/` folders if you encounter any weird behavior.
