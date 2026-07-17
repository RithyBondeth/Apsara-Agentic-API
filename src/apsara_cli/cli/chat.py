from getpass import getpass
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from apsara_cli.shared.types import ResolvedOptions
    from apsara_cli.shared.ui import ConsoleUI

from apsara_cli.shared.events import print_event
from apsara_cli.cli.history import SAFE_INPUT_TOKEN_BUDGET, trim_history_for_request, update_history_from_event
from apsara_cli.cli.input import get_input_async
from apsara_cli.cli.options import resolve_runtime_options
from apsara_cli.cli.session import (
    get_session_path,
    list_sessions,
    load_session_messages,
    sanitize_session_name,
    save_session_messages,
)
from apsara_cli.shared.text import summarize_history  # noqa: F401 (kept for potential external use)
from apsara_cli.shared.ui import ConsoleUI
from apsara_cli.shared.ui import Theme, DEFAULT_THEME
from apsara_cli.engine.tools import agent_runtime_context, get_agent_tools
from apsara_cli.engine.models import (
    MODELS,
    format_context_window,
    is_key_available,
    lookup_model,
    providers_in_order,
    resolve_model_id,
)
from apsara_cli.cli.model_picker import pick_model


def _switch_model(raw_name: str, current_model: str, options: "ResolvedOptions", ui: "ConsoleUI") -> str:
    """
    Resolve ``raw_name`` (a model id or alias) and switch to it, prompting
    for a missing API key when needed. Returns the resolved model id
    (unchanged from ``current_model`` if the switch didn't happen).
    """
    # Resolve alias → canonical model_id
    resolved = resolve_model_id(raw_name)
    entry = lookup_model(raw_name)

    if entry:
        ctx = format_context_window(entry.context_window)
        has_key = is_key_available(entry)
        ui.print_line()
        ui.print_line(
            f"  {ui.style('◆', '38;2;100;150;220')} "
            f"{ui.style(entry.display_name, '1', '38;2;220;225;240')}  "
            f"{ui.dim(entry.model_id)}  {ui.dim(ctx + ' ctx')}"
        )
        if entry.tier == "local":
            ui.print_line(f"  {ui.style('✓ local model — no API key required', '38;2;120;200;150')}")
        elif has_key:
            ui.print_line(f"  {ui.style(f'✓ {entry.env_var} is set', '38;2;120;200;150')}")
        else:
            # ── Prompt for missing API key ─────────────────────────────
            ui.print_line(
                f"  {ui.style('✗', '38;2;220;120;100')} "
                f"{ui.style(entry.env_var, '1', '38;2;255;220;140')} "
                f"{ui.style('is not set', '38;2;220;120;100')}"
            )
            ui.print_line()
            ui.print_line(
                f"  {ui.style('?', '38;2;247;200;100')} "
                f"Enter your {ui.style(entry.env_var, '1', '38;2;255;220;140')} "
                f"{ui.dim('(hidden — press Enter to skip)')}"
            )
            try:
                raw_key = getpass("  → ")
            except (EOFError, KeyboardInterrupt):
                raw_key = ""

            if raw_key.strip():
                os.environ[entry.env_var] = raw_key.strip()
                ui.success(f"{entry.env_var} active for this session.")
                ui.print_line()
                ui.print_line(
                    f"  Save to .env?  "
                    f"{ui.badge('y  save', '17', '48;2;80;170;140')}  "
                    f"{ui.badge('n  session only', '17', '48;2;120;100;80')}"
                )
                save_choice = ui.read_single_key()
                if save_choice in {"y", "Y", "\r", "\n", ""}:
                    try:
                        saved_path = _save_api_key_to_env(
                            options.workspace_root, entry.env_var, raw_key.strip()
                        )
                        ui.success(f"Saved to {saved_path}")
                    except Exception as exc:
                        ui.error(f"Could not write .env: {exc}")
                else:
                    ui.info("Key active for this session only — not saved to disk.")
            else:
                ui.warning(
                    f"No key entered — switching anyway. "
                    f"Add {entry.env_var} to your .env to make it permanent."
                )
        ui.print_line()
    else:
        # Unknown model — allow it but warn
        ui.warning(f"'{raw_name}' is not in the built-in registry (custom/unsupported model).")

    if resolved != current_model:
        ui.info(f"Switched to {ui.style(resolved, '1', '38;2;188;218;255')}")
    return resolved


def build_status_line(options: "ResolvedOptions", current_model: str, session_label: str) -> str:
    """
    Mode · model · session · hint — the single source of truth for the
    bottom status line, shared by the classic REPL toolbar and the TUI
    status bar.
    """
    entry = lookup_model(current_model)
    model_name = entry.display_name if entry else current_model.split("/")[-1]
    if options.dry_run:
        mode = "dry-run"
    elif options.read_only:
        mode = "read-only"
    else:
        mode = "chat"
    return f"{mode} · {model_name} · {session_label}  —  /help commands · esc+enter newline"


def turn_mode_word(options: "ResolvedOptions") -> str:
    """The bold mode word shown in mode lines and turn footers."""
    if options.dry_run:
        return "Dry-run"
    if options.read_only:
        return "Read-only"
    return "Build"


def mode_line_parts(options: "ResolvedOptions", current_model: str) -> tuple[str, str, str]:
    """(mode, model display name, provider) for the input-box mode line."""
    entry = lookup_model(current_model)
    model_name = entry.display_name if entry else current_model.split("/")[-1]
    provider = entry.provider.capitalize() if entry else ""
    return turn_mode_word(options), model_name, provider


def build_mode_line(ui: "ConsoleUI", options: "ResolvedOptions", current_model: str) -> str:
    """
    OpenCode-style mode line rendered under the input:
    'Build · Big Pickle Zhipu' — mode accent-colored, model bold, provider dim.
    """
    mode, model_name, provider = mode_line_parts(options, current_model)
    mode_color = {
        "Dry-run": "38;2;247;200;100",
        "Read-only": "38;2;240;170;90",
    }.get(mode, "38;2;96;150;250")

    parts = [
        ui.style(mode, "1", mode_color),
        ui.dim("·"),
        ui.style(model_name, "1", "38;2;225;230;242"),
    ]
    if provider:
        parts.append(ui.dim(provider))
    return " ".join(parts)


def _load_stored_keys() -> None:
    """Load stored API keys from ~/.apsara/credentials.json into os.environ."""
    import os
    from apsara_cli.cli.auth import get_provider_key
    from apsara_cli.engine.models import providers_in_order as _providers, provider_env_var
    for provider in _providers():
        env_var = provider_env_var(provider)
        if env_var and not os.environ.get(env_var):
            stored = get_provider_key(provider)
            if stored:
                os.environ[env_var] = stored


def _save_api_key_to_env(workspace_root: Path, key_name: str, key_value: str) -> Path:
    """Write or update KEY=value in workspace_root/.env (creates the file if absent)."""
    import re as _re
    env_path = workspace_root / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        pattern = _re.compile(rf"^{_re.escape(key_name)}\s*=.*$", _re.MULTILINE)
        if pattern.search(content):
            new_content = pattern.sub(f"{key_name}={key_value}", content)
        else:
            new_content = content.rstrip("\n") + f"\n{key_name}={key_value}\n"
    else:
        new_content = f"{key_name}={key_value}\n"
    env_path.write_text(new_content, encoding="utf-8")
    return env_path


_HELP_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Conversation", [
        ("/add", "<path>", "Pin a file's contents into the context"),
        ("/history", "", "Show recent conversation turns"),
        ("/details", "", "Reveal the agent's internal steps from the last turn"),
        ("/clear", "", "Clear the in-memory conversation history"),
    ]),
    ("Models & keys", [
        ("/model", "", "Show the current model"),
        ("/model", "<name>", "Switch model (full id or short alias)"),
        ("/models", "[provider]", "Browse all models with key status"),
        ("/key", "list", "Show provider API keys and where they come from"),
        ("/key", "set <provider>", "Add or update a provider API key (hidden input)"),
        ("/key", "remove <provider>", "Delete a stored provider key"),
    ]),
    ("Session", [
        ("/status", "", "Token usage, context health, session cost"),
        ("/save", "", "Save the current session now"),
        ("/session", "", "Show session and workspace details"),
        ("/sessions", "", "List all saved sessions"),
        ("/sessions", "clear [name]", "Delete all sessions, or one by name"),
    ]),
    ("Diagnostics", [
        ("/tools", "", "Show enabled tools with descriptions"),
        ("/bug", "", "Save logs + session state for a bug report"),
        ("/exit", "", "Quit the chat session"),
    ]),
]


def print_chat_help(ui: "ConsoleUI") -> None:
    total = sum(len(cmds) for _, cmds in _HELP_SECTIONS)
    # Column width from the widest "command args" pair, so descriptions align.
    col_w = max(len(f"{c} {a}".strip()) for _, cmds in _HELP_SECTIONS for c, a, _ in cmds) + 3

    ui.print_line()
    ui.print_line(
        f"  {ui.badge('help', '15', '48;2;70;85;115')}  "
        f"{ui.style(f'{total} commands', '38;2;200;210;230')}"
    )
    for section, cmds in _HELP_SECTIONS:
        ui.print_line()
        ui.print_line(f"  {ui.style(section.upper(), '1', '38;2;190;200;220')}")
        for cmd, args, desc in cmds:
            plain = f"{cmd} {args}".strip()
            pad = " " * (col_w - len(plain))
            cmd_styled = ui.style(cmd, "1", "38;2;180;210;255")
            args_styled = f" {ui.style(args, '38;2;247;220;150')}" if args else ""
            ui.print_line(f"    {cmd_styled}{args_styled}{pad}{ui.dim(desc)}")
    ui.print_line()
    ui.print_line(f"  {ui.dim('Esc+Enter newline  ·  ↑/↓ input history  ·  Tab completes /commands')}")
    ui.print_line()


def handle_chat_command(
    command_text: str,
    history: list[dict[str, Any]],
    current_model: str,
    options: "ResolvedOptions",
    config: object,
    ui: "ConsoleUI",
) -> tuple[bool, str]:
    if command_text in {"/exit", "/quit"}:
        turns = sum(1 for m in history if m.get("role") == "user")
        if turns > 0 and options.stateless:
            ui.warning(f"Stateless session — {turns} turn(s) will not be saved.")
            ui.print_line(
                f"  {ui.badge('↵  exit', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  stay', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Staying in session.")
                return True, current_model
        return False, current_model

    if command_text == "/help":
        print_chat_help(ui)
        return True, current_model

    if command_text == "/details":
        ui.show_hidden_events()
        return True, current_model

    if command_text == "/clear":
        history.clear()
        ui.latest_hidden_events = []
        ui.warning("Session cleared in memory")
        return True, current_model

    if command_text == "/bug":
        ui.info("Collecting diagnostic information for bug report...")
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bug_dir = options.workspace_root / ".apsara" / "bugs" / f"bug_{timestamp}"
            bug_dir.mkdir(parents=True, exist_ok=True)
            
            # Save current session
            state_file = bug_dir / "session_state.json"
            state = {
                "model": current_model,
                "history": history,
                "options": {k: str(v) for k, v in vars(options).items()},
            }
            with state_file.open("w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            
            # Copy logs
            if ui.log_file and ui.log_file.exists():
                shutil.copy2(ui.log_file, bug_dir / "session.log")
            
            ui.success(f"Bug report data collected in: {bug_dir}")
            ui.info("Please share this directory with the development team.")
        except Exception as e:
            ui.error(f"Failed to collect bug report data: {e}")
        return True, current_model

    if command_text.startswith("/add "):
        path_str = command_text[len("/add "):].strip()
        if not path_str:
            ui.error("Usage: /add <path>")
            return True, current_model

        from apsara_cli.engine.tools import read_file, _resolve_path, _display_path
        with agent_runtime_context(workspace_root=options.workspace_root):
            try:
                # We use _resolve_path and read_file to respect workspace boundaries
                resolved = _resolve_path(path_str, must_exist=True)
                content = read_file(str(resolved))
                
                if content.startswith("Error"):
                    ui.error(content)
                else:
                    display_p = _display_path(resolved)
                    history.append({
                        "role": "user",
                        "content": f"Please focus on this file: {display_p}\n\nContents of {display_p}:\n```\n{content}\n```",
                    })
                    ui.success(f"Added {display_p} to conversation context.")
            except Exception as e:
                ui.error(f"Could not add file: {e}")
        return True, current_model

    if command_text == "/history":
        if not history:
            ui.info("No conversation history yet.")
            return True, current_model

        total_msgs = len(history)
        user_turns = sum(1 for m in history if m.get("role") == "user")
        turn_plural = "s" if user_turns != 1 else ""
        ui.print_line()
        ui.print_line(
            f"  {ui.badge('history', '15', '48;2;70;85;115')}  "
            f"{ui.style(f'{user_turns} turn{turn_plural}  ·  {total_msgs} messages', '38;2;200;210;230')}"
        )
        ui.print_line()

        turn_num = 0
        i = 0
        while i < len(history):
            msg = history[i]
            role = msg.get("role", "")

            if role == "user":
                turn_num += 1
                content = str(msg.get("content") or "").strip().replace("\n", " ")
                if len(content) > 74:
                    content = content[:71] + "…"
                ui.print_line(
                    f"  {ui.style(f'#{turn_num}', '1', '38;2;180;210;255')}"
                    f"  {ui.style('you', '2', '38;2;130;140;160')}"
                    f"  {ui.style(content, '38;2;230;228;224')}"
                )
                i += 1

                # Collect assistant messages and tool calls for this turn
                tool_call_count = 0
                while i < len(history) and history[i].get("role") != "user":
                    inner = history[i]
                    inner_role = inner.get("role", "")
                    if inner_role == "assistant":
                        tool_calls = inner.get("tool_calls") or []
                        tool_call_count += len(tool_calls)
                        reply = str(inner.get("content") or "").strip().replace("\n", " ")
                        if reply:
                            if len(reply) > 74:
                                reply = reply[:71] + "…"
                            ui.print_line(
                                f"    {ui.style('apsara', '2', '38;2;130;140;160')}"
                                f"  {ui.style(reply, '38;2;210;208;204')}"
                            )
                    i += 1

                if tool_call_count:
                    plural = "s" if tool_call_count != 1 else ""
                    ui.print_line(
                        f"    {ui.dim(f'↳ {tool_call_count} tool call{plural}')}"
                    )
            else:
                i += 1

        ui.print_line()
        return True, current_model

    if command_text == "/tools":
        with agent_runtime_context(
            workspace_root=options.workspace_root,
            enable_bash=options.allow_bash,
            allowed_commands=options.allowed_commands,
            max_file_size_bytes=options.max_file_size,
            dry_run=options.dry_run,
            read_only=options.read_only,
        ):
            tools = get_agent_tools()
        ui.print_line()
        ui.print_line(
            f"  {ui.badge('tools', '15', '48;2;70;85;115')}  "
            f"{ui.style(f'{len(tools)} enabled', '1', '38;2;200;210;230')}"
        )
        ui.print_line()
        for tool in tools:
            fn = tool.get("function", {})
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            ui.print_line(
                f"  {ui.style('◆', '38;2;100;150;220')} "
                f"{ui.style(name, '1', '38;2;180;210;255')}"
            )
            if desc:
                short_desc = desc[:86] + "…" if len(desc) > 86 else desc
                ui.print_line(f"    {ui.dim(short_desc)}")
        ui.print_line()
        return True, current_model

    if command_text == "/models" or command_text.startswith("/models "):
        # ── /models [provider-filter] ──────────────────────────────────────
        filt = command_text[len("/models"):].strip().lower()
        providers = providers_in_order()

        _TIER_COLOR = {
            "free":  ("38;2;120;200;150", "free"),
            "paid":  ("38;2;247;200;100", "paid"),
            "local": ("38;2;160;180;220", "local"),
        }

        header_parts = [ui.badge("models", "15", "48;2;70;85;115")]
        if filt:
            header_parts.append(ui.style(f"filtered: {filt}", "38;2;200;210;230"))
        else:
            total = len(MODELS)
            free_count  = sum(1 for m in MODELS if m.tier in {"free", "local"})
            paid_count  = sum(1 for m in MODELS if m.tier == "paid")
            header_parts.append(
                ui.style(f"{total} models  ·  {free_count} free/local  ·  {paid_count} paid", "38;2;200;210;230")
            )

        # rows: (styled_line, model_id) — model_id is None for non-selectable
        # provider group headers, used both for the interactive picker and
        # (flattened) for the plain-text fallback listing.
        rows: list[tuple[str, Optional[str]]] = []
        shown_any = False
        for provider in providers:
            entries = [m for m in MODELS if m.provider == provider]
            if filt and not any(
                filt in m.model_id.lower() or filt in m.display_name.lower() or filt == m.provider
                for m in entries
            ):
                continue

            provider_rows: list[tuple[str, Optional[str]]] = []
            for entry in entries:
                if filt and filt not in entry.model_id.lower() and filt not in entry.display_name.lower() and filt != provider:
                    continue
                shown_any = True

                is_current = entry.model_id == current_model
                has_key    = is_key_available(entry)
                ctx        = format_context_window(entry.context_window)
                tier_color, tier_label = _TIER_COLOR.get(entry.tier, ("38;2;200;200;200", entry.tier))

                if is_current:
                    status_icon = ui.style("●", "38;2;120;200;150")
                elif has_key or entry.tier == "local":
                    status_icon = ui.style("○", "38;2;140;170;200")
                else:
                    status_icon = ui.style("○", "38;2;120;100;90")

                name_style = ("1", "38;2;220;225;240") if is_current else ("38;2;190;200;220",)
                name_text  = ui.style(entry.display_name, *name_style)
                tier_badge = ui.style(f"[{tier_label}]", tier_color)
                ctx_text   = ui.dim(f"{ctx} ctx")

                if has_key or entry.tier == "local":
                    key_text = ui.style("✓ key set", "38;2;120;200;150")
                else:
                    key_text = ui.style(f"✗ needs {entry.env_var}", "38;2;220;120;100")

                aliases_hint = ""
                if entry.aliases:
                    aliases_hint = "  " + ui.dim("alias: " + ", ".join(entry.aliases[:3]))

                line = (
                    f"{status_icon} {name_text}  {tier_badge}  {ctx_text}  {key_text}  "
                    f"{ui.dim(entry.model_id)}{aliases_hint}"
                )
                provider_rows.append((line, entry.model_id))

            if provider_rows:
                provider_label = ui.style(provider.upper(), "1", "38;2;190;200;220")
                rows.append((provider_label, None))
                rows.extend(provider_rows)

        if not shown_any:
            ui.print_line()
            ui.print_line(f"  {'  '.join(header_parts)}")
            ui.print_line()
            ui.warning(f"No models match '{filt}'. Try a provider name like 'openai', 'groq', 'anthropic'.")
            ui.print_line()
            return True, current_model

        # ── Interactive arrow-key picker (falls back to a plain listing
        # when prompt_toolkit or a real terminal isn't available) ─────────
        if sys.stdout.isatty():
            ui.print_line()
            ui.print_line(f"  {'  '.join(header_parts)}")
            ui.print_line()
            # Under the full-screen TUI, pick_model()'s own transient
            # Application would otherwise contend with the outer one for the
            # terminal — TuiConsoleUI exposes _run_passthrough for exactly
            # this (see tui.py's module docstring).
            run_passthrough = getattr(ui, "_run_passthrough", None)
            if run_passthrough is not None:
                chosen = run_passthrough(lambda: pick_model(rows, current_model, ui))
            else:
                chosen = pick_model(rows, current_model, ui)
            if chosen is None:
                ui.info("No change — model selection cancelled.")
                return True, current_model
            resolved = _switch_model(chosen, current_model, options, ui)
            return True, resolved

        ui.print_line()
        ui.print_line(f"  {'  '.join(header_parts)}")
        ui.print_line()
        for line_text, model_id in rows:
            if model_id is None:
                ui.print_line(f"  {line_text}")
            else:
                ui.print_line(f"    {line_text}")
        ui.print_line()
        ui.print_line(f"  {ui.dim('Switch with /model <id-or-alias>  ·  /models <provider> to filter')}")
        ui.print_line()
        return True, current_model

    if command_text == "/model":
        entry = lookup_model(current_model)
        if entry:
            ctx   = format_context_window(entry.context_window)
            has_k = is_key_available(entry)
            key_s = ui.style("✓ key set", "38;2;120;200;150") if (has_k or entry.tier == "local") else ui.style(f"✗ needs {entry.env_var}", "38;2;220;120;100")
            ui.info(
                f"Current model: {ui.style(entry.display_name, '1', '38;2;220;225;240')}  "
                f"{ui.dim(entry.model_id)}  {ui.dim(ctx + ' ctx')}  {key_s}"
            )
        else:
            ui.info(f"Current model: {current_model}")
        return True, current_model

    if command_text.startswith("/model "):
        raw_name = command_text[len("/model "):].strip()
        if not raw_name:
            ui.error("Usage: /model <model-id-or-alias>")
            return True, current_model

        resolved = _switch_model(raw_name, current_model, options, ui)
        return True, resolved

    if command_text == "/session":
        ui.info(f"Workspace: {options.workspace_root}")
        if options.stateless:
            ui.info("Session mode: stateless")
        else:
            ui.info(f"Session: {sanitize_session_name(options.session)}")
        config_path = getattr(config, "path", None)
        config_exists = getattr(config, "exists", False)
        ui.info(f"Config: {config_path} ({'loaded' if config_exists else 'default values'})")
        return True, current_model

    if command_text == "/save":
        save_if_needed(history, current_model, options, ui)
        return True, current_model

    if command_text == "/sessions" or command_text.startswith("/sessions "):
        sub = command_text[len("/sessions"):].strip()  # "", "clear", or "clear <name>"

        if not sub:
            # ── List all sessions ──────────────────────────────────────────
            sessions = list_sessions(options.workspace_root)
            if not sessions:
                ui.info("No saved sessions found.")
                return True, current_model

            current_name = (
                sanitize_session_name(options.session) if not options.stateless else None
            )
            ui.print_line()
            ui.print_line(
                f"  {ui.badge('sessions', '15', '48;2;70;85;115')}  "
                f"{ui.style(f'{len(sessions)} saved', '38;2;200;210;230')}"
            )
            ui.print_line()
            for path in sessions:
                name = path.stem
                is_current = name == current_name
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    msg_count = len(payload.get("messages", []))
                    updated_at = payload.get("updated_at", "")[:19].replace("T", " ")
                    model_name = payload.get("model", "?")
                except Exception:
                    msg_count, updated_at, model_name = 0, "?", "?"
                size_kb = path.stat().st_size / 1024
                current_marker = ui.style("  ← active", "38;2;120;200;150") if is_current else ""
                ui.print_line(
                    f"  {ui.style('◆', '38;2;100;150;220')} "
                    f"{ui.style(name, '1', '38;2;180;210;255')}"
                    f"{current_marker}"
                )
                ui.print_line(
                    f"    {ui.dim(f'{msg_count} messages  ·  {updated_at}  ·  {size_kb:.1f} kb  ·  {model_name}')}"
                )
            ui.print_line()
            ui.print_line(f"  {ui.dim('  /sessions clear         delete all sessions')}")
            ui.print_line(f"  {ui.dim('  /sessions clear <name>  delete a specific session')}")
            ui.print_line()
            return True, current_model

        if sub == "clear":
            # ── Delete all sessions ────────────────────────────────────────
            sessions = list_sessions(options.workspace_root)
            if not sessions:
                ui.info("No saved sessions to clear.")
                return True, current_model

            ui.warning(f"This will permanently delete {len(sessions)} session file(s).")
            ui.print_line(
                f"  {ui.badge('↵  confirm', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  cancel', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Cancelled.")
                return True, current_model

            deleted = 0
            for path in sessions:
                try:
                    path.unlink()
                    deleted += 1
                except Exception as exc:
                    ui.error(f"Could not delete {path.name}: {exc}")
            ui.success(f"Deleted {deleted} session file(s).")
            return True, current_model

        if sub.startswith("clear "):
            # ── Delete one session by name ─────────────────────────────────
            target_name = sub[len("clear "):].strip()
            if not target_name:
                ui.error("Usage: /sessions clear <name>")
                return True, current_model

            target_path = get_session_path(options.workspace_root, target_name)
            if not target_path.exists():
                ui.error(f"Session '{target_name}' not found.")
                return True, current_model

            ui.warning(f"Delete session '{target_name}'?")
            ui.print_line(
                f"  {ui.badge('↵  confirm', '17', '48;2;80;170;140')}  "
                f"{ui.badge('n  cancel', '17', '48;2;200;100;80')}"
            )
            key = ui.read_single_key()
            if key not in {"y", "Y", "\r", "\n", ""}:
                ui.info("Cancelled.")
                return True, current_model

            try:
                target_path.unlink()
                ui.success(f"Session '{target_name}' deleted.")
            except Exception as exc:
                ui.error(f"Could not delete session: {exc}")
            return True, current_model

        ui.error("Usage: /sessions  |  /sessions clear  |  /sessions clear <name>")
        return True, current_model

    if command_text == "/status":
        from apsara_cli.engine.executor import SYSTEM_PROMPT
        from apsara_cli.engine.llm import estimate_request_tokens

        base = [{"role": "system", "content": SYSTEM_PROMPT}]
        tokens = estimate_request_tokens(base + history, model=current_model)
        pct = int(tokens / SAFE_INPUT_TOKEN_BUDGET * 100)
        turns = sum(1 for m in history if m.get("role") == "user")
        msgs = len(history)
        session_label = (
            sanitize_session_name(options.session) if not options.stateless else "stateless"
        )
        cost = ui.calculate_session_cost()

        if pct < 70:
            health_color = "38;2;120;200;150"
            health_label = "good"
        elif pct < 90:
            health_color = "38;2;247;223;181"
            health_label = "warn"
        else:
            health_color = "38;2;255;168;168"
            health_label = "critical"

        ui.print_line()
        ui.print_line(
            f"  {ui.badge('status', '15', '48;2;70;85;115')}  "
            f"{ui.style('Session Context', '1', '38;2;200;210;230')}"
        )
        ui.print_line()
        
        # Governance flags
        if options.dry_run or options.read_only:
            flags = []
            if options.dry_run: flags.append(ui.style("DRY-RUN", "1", "38;2;247;200;100"))
            if options.read_only: flags.append(ui.style("READ-ONLY", "1", "38;2;220;120;100"))
            ui.print_line(f"  {ui.dim('  active   ')} {' '.join(flags)}")

        ui.print_line(f"  {ui.dim('  model    ')} {ui.style(current_model, '38;2;188;218;255')}")
        ui.print_line(f"  {ui.dim('  session  ')} {ui.style(session_label, '38;2;220;216;210')}")
        ui.print_line(f"  {ui.dim('  turns    ')} {ui.style(str(turns), '38;2;220;216;210')}")
        ui.print_line(f"  {ui.dim('  messages ')} {ui.style(str(msgs), '38;2;220;216;210')}")
        ui.print_line(
            f"  {ui.dim('  tokens   ')} "
            f"{ui.style(f'{tokens:,}', health_color)} "
            f"{ui.dim(f'/ {SAFE_INPUT_TOKEN_BUDGET:,} budget  ({pct}%  {health_label})')}"
        )
        ui.print_line(f"  {ui.dim('  cost     ')} {ui.style(f'${cost:.4f}', '38;2;120;200;150')} {ui.dim('(est. session total)')}")
        ui.print_line()
        return True, current_model

    if command_text == "/key" or command_text.startswith("/key "):
        from apsara_cli.cli.auth import (
            get_active_provider,
            get_provider_key,
            remove_provider_key,
            save_provider_key,
            stored_providers,
        )
        from apsara_cli.engine.models import (
            KEY_HINTS,
            default_model_for_provider,
            provider_env_var,
            validate_key_format,
        )

        sub = command_text[len("/key"):].strip()
        keyed_providers = [p for p in providers_in_order() if provider_env_var(p)]

        if sub in {"", "list"}:
            active = get_active_provider()
            ui.print_line()
            ui.print_line(
                f"  {ui.badge('keys', '15', '48;2;70;85;115')}  "
                f"{ui.style('Provider API keys', '38;2;200;210;230')}"
            )
            ui.print_line()
            for provider in keyed_providers:
                env_var = provider_env_var(provider)
                in_store = get_provider_key(provider) is not None
                in_env = bool(os.environ.get(env_var))
                if in_store:
                    icon, source = ui.style("●", "38;2;120;200;150"), "stored in ~/.apsara"
                elif in_env:
                    icon, source = ui.style("●", "38;2;140;190;240"), f"from env {env_var}"
                else:
                    icon, source = ui.style("○", "38;2;120;100;90"), "not set"
                active_marker = ui.style("  ← active", "38;2;120;200;150") if provider == active else ""
                name = ui.style(provider.ljust(11), "1", "38;2;220;225;240")
                ui.print_line(f"    {icon} {name}{ui.dim(source)}{active_marker}")
            ui.print_line()
            ui.print_line(f"  {ui.dim('/key set <provider> to add  ·  /key remove <provider> to delete')}")
            ui.print_line()
            return True, current_model

        if sub.startswith("set"):
            provider = sub[len("set"):].strip().lower()
            if provider not in keyed_providers:
                ui.error(f"Usage: /key set <provider>  —  one of: {', '.join(keyed_providers)}")
                return True, current_model

            env_var = provider_env_var(provider)
            hint = KEY_HINTS.get(env_var)
            ui.print_line()
            ui.print_line(
                f"  {ui.style('?', '38;2;247;200;100')} "
                f"Enter your {ui.style(provider, '1', '38;2;220;225;240')} API key "
                f"{ui.dim('(hidden — Enter to cancel)')}"
            )
            if hint and hint[1]:
                ui.print_line(f"    {ui.dim(hint[1])}")
            try:
                raw_key = getpass("  → ").strip()
            except (EOFError, KeyboardInterrupt):
                raw_key = ""
            if not raw_key:
                ui.info("Cancelled — no key saved.")
                return True, current_model

            looks_valid, message = validate_key_format(env_var, raw_key)
            if not looks_valid:
                ui.warning(f"That doesn't match the usual format. {message}")
                ui.print_line(
                    f"  {ui.badge('↵  save anyway', '17', '48;2;80;170;140')}  "
                    f"{ui.badge('n  cancel', '17', '48;2;200;100;80')}"
                )
                if ui.read_single_key() not in {"y", "Y", "\r", "\n", ""}:
                    ui.info("Cancelled — no key saved.")
                    return True, current_model

            save_provider_key(provider, api_key=raw_key, default_model=default_model_for_provider(provider))
            os.environ[env_var] = raw_key
            ui.success(f"Saved {provider} key to ~/.apsara/credentials.json — active now.")
            default_model = default_model_for_provider(provider)
            if default_model and default_model != current_model:
                ui.print_line(f"  {ui.dim(f'Try /model {default_model} to switch, or /models {provider} to browse.')}")
            return True, current_model

        if sub.startswith("remove"):
            provider = sub[len("remove"):].strip().lower()
            if not provider:
                stored = stored_providers()
                hint = f"stored: {', '.join(stored)}" if stored else "no keys stored"
                ui.error(f"Usage: /key remove <provider>  —  {hint}")
                return True, current_model
            if remove_provider_key(provider):
                env_var = provider_env_var(provider)
                if env_var:
                    os.environ.pop(env_var, None)
                ui.success(f"Removed stored {provider} key.")
            else:
                ui.warning(f"No stored key for '{provider}'. /key list to see what's saved.")
            return True, current_model

        ui.error("Usage: /key list  |  /key set <provider>  |  /key remove <provider>")
        return True, current_model

    # Unknown command — suggest the closest match instead of a bare error.
    import difflib
    known = [c for c, _, _ in (cmd for _, cmds in _HELP_SECTIONS for cmd in cmds)]
    word = command_text.split()[0]
    matches = difflib.get_close_matches(word, set(known), n=1, cutoff=0.5)
    suggestion = f" Did you mean {matches[0]}?" if matches else ""
    ui.error(f"Unknown command '{word}'.{suggestion} Type /help for the full list.")
    return True, current_model


async def execute_instruction(
    instruction: str,
    model: str,
    history: list[dict[str, Any]],
    options: "ResolvedOptions",
    ui: "ConsoleUI",
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    from apsara_cli.engine.executor import run_agent_stream
    from apsara_cli.engine.llm import DEFAULT_MAX_COMPLETION_TOKENS

    next_history = list(history)
    next_history.append({"role": "user", "content": instruction})
    latest_usage = None
    ui.begin_turn()

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=None if options.auto_approve else ui.confirm_action,
        dry_run=options.dry_run,
        read_only=options.read_only,
    ):
        trim_result = await trim_history_for_request(next_history, model=model)
        if trim_result.dropped_turns:
            ui.warning(
                f"Trimmed {trim_result.dropped_turns} earlier turn(s) "
                f"({trim_result.dropped_messages} messages) to stay within the request budget."
            )
            if trim_result.summary:
                ui.info(f"Generated summary of earlier conversation: {ui.dim(trim_result.summary[:100] + '...')}")
            
            ui.info(
                f"Estimated input tokens: {trim_result.original_tokens} -> {trim_result.trimmed_tokens}. "
                f"Response budget capped at about {DEFAULT_MAX_COMPLETION_TOKENS} tokens."
            )
            # Use the trimmed history (including summary) for the rest of this turn
            next_history = list(trim_result.request_history)

        async for chunk_str in run_agent_stream(next_history, model=model):
            event = json.loads(chunk_str)
            if event.get("type") == "usage":
                latest_usage = event.get("data")
            else:
                print_event(event, ui)
                update_history_from_event(next_history, event)

    entry = lookup_model(model)
    ui.finish_turn(
        model_label=entry.display_name if entry else model.split("/")[-1],
        mode=turn_mode_word(options),
    )
    return next_history, latest_usage


def save_if_needed(
    history: list[dict[str, Any]],
    model: str,
    options: "ResolvedOptions",
    ui: "ConsoleUI",
) -> None:
    if options.stateless:
        return
    session_path = save_session_messages(
        workspace_root=options.workspace_root,
        session_name=options.session,
        model=model,
        messages=history,
    )
    ui.session_saved(session_path)


async def run_once(args: object, config: object) -> int:
    options = resolve_runtime_options(args, config.defaults)

    # Load stored API keys into environment so litellm can use them
    _load_stored_keys()

    # Build theme from config overrides
    theme = Theme()
    config_theme = getattr(config, "theme", None)
    if config_theme is not None:
        config_theme.apply_to(theme)

    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve, theme=theme)
    history: list[dict[str, Any]] = []

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    updated_history, latest_usage = await execute_instruction(
        instruction=args.instruction,
        model=options.model,
        history=history,
        options=options,
        ui=ui,
    )

    save_if_needed(updated_history, options.model, options, ui)
    if latest_usage and latest_usage.get("total_tokens") is not None:
        ui.usage(latest_usage)

    return 0


async def chat_loop(args: object, config: object) -> int:
    from apsara_cli.cli.banner import print_welcome_banner

    options = resolve_runtime_options(args, config.defaults)

    # Load stored API keys into environment so litellm can use them
    _load_stored_keys()

    # Build theme from config overrides
    theme = Theme()
    config_theme = getattr(config, "theme", None)
    if config_theme is not None:
        config_theme.apply_to(theme)

    ui = ConsoleUI(use_color=options.use_color, auto_approve=options.auto_approve, theme=theme)
    history: list[dict[str, Any]] = []
    current_model = options.model
    turn_count = 0

    if not options.stateless:
        history = load_session_messages(options.workspace_root, options.session)

    print_welcome_banner(ui, config)

    # ── OpenCode-style welcome chrome: hints, tip, footer ─────────────────
    from apsara_cli.cli.auth import get_active_provider
    from apsara_cli.shared.ui import terminal_width
    from apsara_cli import __version__

    _terminal = max(48, min(terminal_width(), 112))

    def _center_pad(plain_len: int) -> str:
        return " " * max((_terminal - plain_len) // 2, 2)

    session_label = sanitize_session_name(options.session) if not options.stateless else "stateless"
    _active_provider = get_active_provider()
    _model_entry = lookup_model(current_model)
    _key_ok = _model_entry is not None and (
        is_key_available(_model_entry) or _model_entry.tier == "local"
    )

    # Keyboard hints, 'tab agents  ctrl+p commands' style.
    _hints = [("/", "commands"), ("esc+enter", "newline"), ("↑↓", "history")]
    _hints_plain = "   ".join(f"{key} {label}" for key, label in _hints)
    _hints_styled = "   ".join(
        f"{ui.style(key, '1', '38;2;140;180;255')} {ui.dim(label)}" for key, label in _hints
    )
    ui.print_line(_center_pad(len(_hints_plain)) + _hints_styled)

    if history:
        prior_turns = sum(1 for m in history if m.get("role") == "user")
        plural = "s" if prior_turns != 1 else ""
        _resumed = f"resumed {prior_turns} prior turn{plural}"
        ui.print_line()
        ui.print_line(_center_pad(len(_resumed)) + ui.dim(_resumed))
        turn_count = prior_turns

    # Tip line: '● Tip Run /key set … to add an AI provider and start coding'.
    _needs_setup = not _active_provider and _model_entry is not None and not _key_ok
    if _needs_setup:
        _tip_cmd = f"/key set {_model_entry.provider}"
        _tip_rest = "to add an AI provider and start coding"
        _tip_plain = f"● Tip Run {_tip_cmd} {_tip_rest}"
        _tip_styled = (
            f"{ui.style('●', '38;2;240;170;90')} {ui.style('Tip', '1', '38;2;240;170;90')} "
            f"{ui.style('Run', '38;2;200;205;215')} {ui.style(_tip_cmd, '1', '38;2;225;230;242')} "
            f"{ui.style(_tip_rest, '38;2;200;205;215')}"
        )
    else:
        _tip_rest = 'Ask anything — e.g. "What is the tech stack of this project?"'
        _tip_plain = f"● Tip {_tip_rest}"
        _tip_styled = (
            f"{ui.style('●', '38;2;240;170;90')} {ui.style('Tip', '1', '38;2;240;170;90')} "
            f"{ui.style(_tip_rest, '38;2;200;205;215')}"
        )
    ui.print_line()
    ui.print_line(_center_pad(len(_tip_plain)) + _tip_styled)

    # First-run guidance, styled like OpenCode's 'Getting started' card.
    if _needs_setup:
        _gs_w = min(_terminal - 8, 56)
        ui.print_line()
        ui.print_line(f"  {ui.style('◇ Getting started', '1', '38;2;130;170;250')}")
        ui.print_line()
        _gs_body = (
            "Apsara includes free-tier and local models so you can start "
            "quickly. Connect a provider to use other models, including "
            "Claude, GPT, Gemini etc."
        )
        import textwrap as _tw
        for _line in _tw.wrap(_gs_body, width=_gs_w):
            ui.print_line(f"    {ui.dim(_line)}")
        ui.print_line()
        _gs_cmd = f"/key set {_model_entry.provider}"
        _gs_gap = " " * max(_gs_w - len("Connect provider") - len(_gs_cmd), 2)
        ui.print_line(
            f"    {ui.style('Connect provider', '1', '38;2;225;230;242')}"
            f"{_gs_gap}{ui.style(_gs_cmd, '1', '38;2;180;210;255')}"
        )

    # Bottom footer: workspace path left, session · version right, with
    # colored accents (⌂ gold, session green, version violet).
    _left_plain = f"⌂ {options.workspace_root}"
    _right_plain = f"{session_label} · v{__version__}"
    _gap = max(_terminal - len(_left_plain) - len(_right_plain) - 4, 2)
    _left_styled = f"{ui.style('⌂', '38;2;240;190;110')} {ui.dim(str(options.workspace_root))}"
    _right_styled = (
        f"{ui.style(session_label, '38;2;130;210;160')}{ui.dim(' · ')}"
        f"{ui.style('v' + __version__, '38;2;190;150;250')}"
    )
    ui.print_line()
    ui.print_line(f"  {_left_styled}{' ' * _gap}{_right_styled}")

    _BOX_BORDER = "38;2;90;108;180"  # soft indigo, matches the TUI input box

    while True:
        # OpenCode-style typing box: a rounded top border, a padding row, and
        # a '│▌' gutter are part of the prompt itself; the bottom toolbar
        # draws the box's lower edge carrying the 'Build · Model' mode line.
        _w = max(40, min(terminal_width() - 2, 110))
        _mode, _model_name, _provider = mode_line_parts(options, current_model)
        _mode_plain = f"{_mode} · {_model_name}" + (f" {_provider}" if _provider else "")
        _fill = max(_w - len(_mode_plain) - 6, 1)
        _toolbar = (
            ui.style("╰─ ", _BOX_BORDER)
            + build_mode_line(ui, options, current_model)
            + " "
            + ui.style("─" * _fill + "╯", _BOX_BORDER)
        )
        _prompt = (
            "\n"
            + ui.style("╭" + "─" * (_w - 2) + "╮", _BOX_BORDER)
            + "\n"
            + ui.style("│", _BOX_BORDER)
            + "\n"
            + ui.style("│", _BOX_BORDER)
            + ui.style("▌", ui.theme.accent)
            + " "
        )
        try:
            instruction = (
                await get_input_async(_prompt, options.workspace_root, toolbar=_toolbar)
            ).strip()
        except KeyboardInterrupt:
            ui.print_line()
            ui.info("Ctrl+C pressed. Type /exit to quit.")
            continue
        except EOFError:
            ui.print_line()
            break

        if not instruction:
            continue
        if instruction.startswith("/"):
            should_continue, current_model = handle_chat_command(
                instruction, history, current_model, options, config, ui
            )
            if not should_continue:
                break
            continue

        turn_count += 1

        # Proactive token budget warning before executing
        try:
            from apsara_cli.engine.executor import SYSTEM_PROMPT
            from apsara_cli.engine.llm import estimate_request_tokens
            _base = [{"role": "system", "content": SYSTEM_PROMPT}]
            _curr_tokens = estimate_request_tokens(_base + history, model=current_model)
            _warn_threshold = int(SAFE_INPUT_TOKEN_BUDGET * 0.75)
            if _curr_tokens >= _warn_threshold:
                _pct = int(_curr_tokens / SAFE_INPUT_TOKEN_BUDGET * 100)
                ui.warning(
                    f"Context at {_pct}% capacity ({_curr_tokens:,} / {SAFE_INPUT_TOKEN_BUDGET:,} tokens). "
                    "Oldest turns may be trimmed — use /clear to reset."
                )
        except Exception:
            pass

        ui.print_turn_separator(turn_count)

        history, latest_usage = await execute_instruction(
            instruction=instruction,
            model=current_model,
            history=history,
            options=options,
            ui=ui,
        )

        save_if_needed(history, current_model, options, ui)
        if latest_usage and latest_usage.get("total_tokens") is not None:
            ui.usage(latest_usage)

    return 0
