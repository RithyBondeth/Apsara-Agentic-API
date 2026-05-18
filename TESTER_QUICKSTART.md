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

## 2. Configuration

Apsara needs an API key to work. You can use Groq (recommended for speed), OpenAI, or Anthropic.

```bash
# Export your key (or add it to a .env file later)
export GROQ_API_KEY="your_key_here"
```

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
