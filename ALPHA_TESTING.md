# Apsara by Bondeth Alpha Testing Guide

This guide is for early testers of the local CLI.

Use this when you want someone to:

- install the project locally
- confirm the CLI works end to end
- try real coding-assistant workflows
- report bugs and rough edges clearly

## 1. Tester Goal

The goal of alpha testing is not to prove everything is perfect.

The goal is to answer:

- Can a new tester install it successfully?
- Can they start a session without getting stuck?
- Does Apsara feel useful for real coding tasks?
- Do edit approvals and patch review feel safe and understandable?
- What breaks first?

## 2. Best Test Audience

Start with 3 to 10 trusted testers who:

- are comfortable using the terminal
- can create an OpenAI API key with billing enabled
- regularly work in local codebases
- are willing to share screenshots and error messages

## 3. Prerequisites

Each tester should have:

- Python 3.9 or newer
- a local terminal
- an OpenAI API key with active billing
- a repo or sample project they can safely test on

Optional but recommended:

- `rg` installed for better search tool behavior
- a preferred editor set in `$EDITOR` or `$VISUAL`

## 4. Quick Start For Testers

1. Clone or open the project:

```bash
cd "/Users/bondeth/Projects/Apsara Agentic/apsara-agentic-cli"
```

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

1. Optional: install the CLI command:

```bash
python3 -m pip install -e .
```

If that fails, testers can still use:

```bash
python3 -m app.cli
```

1. Add the API key to `.env`:

```env
OPENAI_API_KEY=your_openai_api_key
```

1. Run the health check:

```bash
python3 -m app.cli doctor --workspace .
```

1. Initialize the project and start the CLI:

```bash
python3 -m app.cli init --workspace . --model gpt-5.4-mini
```

## 5. First-Test Script

Ask testers to try these in order.

### Test A: Basic Prompt

Run:

```text
Describe this project.
```

Expected result:

- Apsara starts normally
- the loading state appears
- the final answer is readable and organized

### Test B: Workspace Understanding

Run:

```text
Find the main CLI file and summarize what it does.
```

Expected result:

- Apsara searches the workspace
- the answer mentions the correct file
- the answer is clean without too much internal noise

### Test C: Proposed Code Change

Run:

```text
Suggest one small improvement to the CLI UI and implement it.
```

Expected result:

- Apsara proposes a file change
- a diff preview appears before approval
- `v` shows a larger terminal diff
- `e` opens the patch in the tester's editor
- `Enter` approves or `n` rejects cleanly

### Test D: Fresh Session Safety

Run:

```text
/clear
```

Then ask a new prompt.

Expected result:

- the prior conversation is cleared for the active session
- the new response does not depend on old chat context

### Test E: Hidden Internal Activity

Run:

```text
/details
```

Expected result:

- hidden tool or planning activity is visible on demand
- the default chat remains cleaner than the detail view

## 6. What Testers Should Watch For

Please ask testers to report:

- setup friction
- confusing output
- poor formatting in long answers
- approval prompts that feel unclear
- incorrect file changes
- missing or broken diff previews
- editor preview not opening
- rate limit or billing errors
- slow responses
- anything that feels unsafe or surprising

## 7. Known Alpha Notes

Testers should know:

- this is an alpha CLI, not a final public release
- the `apsara` command may fail on older packaging setups, but `python3 -m app.cli` should still work
- live model access depends on the tester's own API billing and rate limits
- automated tests are still limited

## 8. Feedback Template

Ask testers to send feedback in this format:

```text
Name:
OS + terminal:
Python version:
How I launched it:
What I asked Apsara to do:
What worked well:
What felt confusing:
Any error message:
Did edit review feel safe:
Would I use it again:
Screenshot or terminal paste:
```

## 9. Alpha Release Checklist For Bondeth

Before sharing with testers, confirm:

- `.env` loading works
- `python3 -m app.cli doctor --workspace .` works
- `python3 -m app.cli chat --workspace . --model gpt-5.4-mini` works
- the welcome screen renders nicely
- the loading animation appears while the agent is working
- assistant responses are readable
- code edits show a diff preview
- `v` shows a fuller diff
- `e` opens the patch in `$EDITOR` or `$VISUAL`
- `Enter`, `n`, and `a` work in approval prompts
- `/details` works
- `/clear` works

## 10. Recommended Share Message

You can send testers this:

```text
I’m testing an early version of Apsara by Bondeth, a local coding assistant CLI. I’d love your help trying the setup, asking it a few coding questions, and testing one safe code edit workflow. Please send me any rough edges, confusing UX moments, screenshots, or errors you hit.
```

## 11. Related Docs

- Alpha release notes: [RELEASE_NOTES_ALPHA.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-cli/RELEASE_NOTES_ALPHA.md)
- Tester quickstart: [TESTER_QUICKSTART.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-cli/TESTER_QUICKSTART.md)
- Run guide: [RUN_PROJECT.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-cli/RUN_PROJECT.md)
- Main project README: [README.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-cli/README.md)
- CLI entrypoint: [src/cli.py](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-cli/src/cli.py)
