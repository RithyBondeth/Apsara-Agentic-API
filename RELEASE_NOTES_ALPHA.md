# Apsara by Bondeth Alpha Release Notes

Version: `0.1.0-alpha`

Date: `2026-04-07`

## Overview

This alpha release introduces the first polished local CLI experience for Apsara by Bondeth.

The focus of this release is:
- local coding assistant workflows
- safer code-edit review
- better terminal presentation
- faster tester onboarding

## Highlights

### Branded CLI Experience

- custom Apsara welcome screen
- colorful terminal styling
- branded identity with `Apsara by Bondeth`
- loading animation while the agent is working

### Better Chat Experience

- cleaner assistant response formatting
- hidden internal tool chatter by default
- `/details` to inspect hidden activity on demand
- local session history with trimming for oversized requests

### Safer Code Editing

- approval prompts before file writes and command execution
- diff preview before code changes are applied
- `v` to inspect a fuller diff in the terminal
- `e` to open the proposed patch in `$EDITOR` or `$VISUAL`

### Local CLI Workflow

- `init` command for project-first setup
- `doctor` command for environment checks
- `chat`, `run`, and `sessions` commands
- automatic `.env` loading for local use
- workspace-scoped tools and optional allowlisted bash execution

### Tester Support

- step-by-step run guide
- alpha testing guide
- tester quickstart

## Recommended Test Areas

Please focus alpha feedback on:
- first-run setup
- CLI readability and overall UX
- response organization
- code-edit approval flow
- editor-based patch review
- failure handling for missing keys, billing limits, and rate limits

## Known Alpha Limitations

- live model usage still depends on the tester's own API key, billing, and rate limits
- the `apsara` shell command may still be less reliable than `python3 -m app.cli` on older packaging setups
- automated test coverage is still limited
- this is ready for private alpha testing, not a wide public launch

## Suggested Launch Positioning

Recommended label:

`Apsara by Bondeth - Private Alpha`

Recommended audience:

- trusted developer friends
- technical early adopters
- small internal testing group

## Related Docs

- Tester quickstart: [TESTER_QUICKSTART.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/TESTER_QUICKSTART.md)
- Alpha testing guide: [ALPHA_TESTING.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/ALPHA_TESTING.md)
- Run guide: [RUN_PROJECT.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/RUN_PROJECT.md)
- Main README: [README.md](/Users/bondeth/Projects/Apsara%20Agentic/apsara-agentic-api/README.md)
