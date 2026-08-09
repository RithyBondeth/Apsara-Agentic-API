# Apsara by Bondeth Alpha Release Notes

Version: `0.1.0a1`

Date: `2026-08-08`

## Overview

This alpha release introduces the first polished local CLI experience for Apsara by Bondeth.

The focus of this release is:

- local coding assistant workflows
- safer code-edit review
- better terminal presentation
- faster tester onboarding

## Highlights

### Default Model

- OpenCode Zen's `opencode/big-pickle` is the default model
- `apsara login` supports OpenCode Zen and stores its key locally
- other LiteLLM-compatible models remain selectable with `--model`

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
- typed run state, durable redacted journals, run reports, and evaluation suites
- planning and verification gates for multi-step coding tasks

### Safer Code Editing

- approval prompts before file writes and command execution
- `--auto-approve` is limited to workspace file mutations; commands,
  background processes, project code, and external mutations still ask
- diff preview before code changes are applied
- `v` to inspect a fuller diff in the terminal
- `e` to open the proposed patch in `$EDITOR` or `$VISUAL`
- workspace-scoped parallel reads with context isolation
- checkpoints and undo support for agent edits
- process-group cleanup for background commands
- nested interpreter validation so `python -m pip` cannot bypass the command allowlist
- MCP approvals are invalidated when execution environment values or HTTP
  headers change

### Local CLI Workflow

- `init` command for project-first setup
- `doctor` command for environment checks
- `chat`, `run`, and `sessions` commands
- automatic `.env` loading for local use
- workspace-scoped tools and optional allowlisted bash execution
- repository maps, symbol search, project memory, git tools, and MCP governance
- background process management and bounded output capture
- model fallback support and JSON plugin manifests

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
- OpenCode currently warns against sending confidential code to Big Pickle
- this remains an alpha release; users should review proposed changes and keep Git backups

## Suggested Launch Positioning

Recommended label:

`Apsara by Bondeth - Private Alpha`

Recommended audience:

- trusted developer friends
- technical early adopters
- small internal testing group

## Related Docs

- Tester quickstart: [TESTER_QUICKSTART.md](TESTER_QUICKSTART.md)
- Alpha testing guide: [ALPHA_TESTING.md](ALPHA_TESTING.md)
- Run guide: [RUN_PROJECT.md](RUN_PROJECT.md)
- Main README: [README.md](README.md)
