import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.cli.types import ResolvedOptions
    from app.cli.ui import ConsoleUI

from app.cli.types import DoctorCheckResult
from app.cli.options import detect_model_credentials
from app.services.agent.tools import agent_runtime_context, execute_tool, get_agent_tools


def render_doctor_result(ui: "ConsoleUI", result: DoctorCheckResult) -> None:
    label = f"[{result.status.upper()}] {result.name}: {result.detail}"
    if result.status == "pass":
        ui.success(label)
    elif result.status == "warn":
        ui.warning(label)
    else:
        ui.error(label)


def run_workspace_checks(
    options: "ResolvedOptions",
    config: object,
    args: object,
) -> list[DoctorCheckResult]:
    from app.cli.session import get_sessions_dir

    results = []

    if sys.version_info >= (3, 9):
        results.append(DoctorCheckResult("python", "pass", f"Python {sys.version.split()[0]} is supported."))
    else:
        results.append(DoctorCheckResult("python", "fail", f"Python {sys.version.split()[0]} is below the required 3.9+."))

    config_path = getattr(config, "path", None)
    config_exists = getattr(config, "exists", False)
    args_config = getattr(args, "config", None)

    if config_exists:
        results.append(DoctorCheckResult("config", "pass", f"Loaded config from {config_path}."))
    elif args_config:
        results.append(DoctorCheckResult("config", "fail", f"Config file was requested but not found at {config_path}."))
    else:
        results.append(DoctorCheckResult("config", "warn", f"No config file found at {config_path}; using defaults and CLI flags."))

    if options.workspace_root.exists() and options.workspace_root.is_dir():
        results.append(DoctorCheckResult("workspace", "pass", f"Workspace exists at {options.workspace_root}."))
    elif options.workspace_root.exists():
        results.append(DoctorCheckResult("workspace", "fail", f"Workspace path exists but is not a directory: {options.workspace_root}."))
    else:
        results.append(DoctorCheckResult("workspace", "fail", f"Workspace does not exist: {options.workspace_root}."))
        return results

    try:
        session_dir = get_sessions_dir(options.workspace_root)
        session_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=str(session_dir), prefix="doctor-", suffix=".tmp", delete=False) as f:
            f.write("ok")
            temp_path = Path(f.name)
        temp_path.unlink(missing_ok=True)
        status = "pass" if not options.stateless else "warn"
        detail = (
            f"Session storage is writable at {session_dir}."
            if not options.stateless
            else f"Session storage is writable at {session_dir}, but stateless mode is enabled."
        )
        results.append(DoctorCheckResult("session-store", status, detail))
    except Exception as exc:
        results.append(DoctorCheckResult("session-store", "fail", f"Could not write session data: {exc}"))

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=lambda action, payload: False,
    ):
        tool_names = [tool["function"]["name"] for tool in get_agent_tools()]
        results.append(DoctorCheckResult("tools", "pass", f"Enabled tools: {', '.join(tool_names)}"))

        structure_result = execute_tool("list_project_structure", {"root_dir": "."})
        if structure_result.startswith("Error"):
            results.append(DoctorCheckResult("workspace-scan", "fail", structure_result))
        else:
            results.append(DoctorCheckResult("workspace-scan", "pass", "Workspace structure scan succeeded."))

        if options.allow_bash:
            default_command = "pwd"
            if options.allowed_commands and default_command not in options.allowed_commands:
                default_command = sorted(options.allowed_commands)[0]
            command_result = execute_tool("run_bash_command", {"command": default_command})
            if "not approved" in command_result:
                results.append(DoctorCheckResult(
                    "bash-tool", "pass",
                    f"Bash tool is enabled with allowlist {', '.join(sorted(options.allowed_commands or set()))}; "
                    "approval prompt would be required during normal use.",
                ))
            elif command_result.startswith("Error"):
                results.append(DoctorCheckResult("bash-tool", "fail", command_result))
            else:
                results.append(DoctorCheckResult("bash-tool", "pass", f"Bash tool is enabled and command '{default_command}' succeeded."))
        else:
            results.append(DoctorCheckResult("bash-tool", "warn", "Bash tool is disabled. Use --allow-bash if you want command execution."))

    provider, env_vars, note = detect_model_credentials(options.model)
    if env_vars is None:
        status = "pass" if provider == "ollama" else "warn"
        results.append(DoctorCheckResult("credentials", status, note))
    else:
        present = [ev for ev in env_vars if os.environ.get(ev)]
        if present:
            results.append(DoctorCheckResult("credentials", "pass", f"{note} Found {', '.join(present)}."))
        else:
            results.append(DoctorCheckResult("credentials", "fail", f"{note} Missing any of: {', '.join(env_vars)}."))

    return results


async def run_live_probe(options: "ResolvedOptions") -> DoctorCheckResult:
    from app.services.agent.llm import call_llm

    probe_messages = [{"role": "user", "content": "Reply with the single word READY."}]

    with agent_runtime_context(
        workspace_root=options.workspace_root,
        enable_bash=options.allow_bash,
        allowed_commands=options.allowed_commands,
        max_file_size_bytes=options.max_file_size,
        confirmation_callback=lambda action, payload: False,
    ):
        response_message, usage = await asyncio.wait_for(
            call_llm(probe_messages, model=options.model), timeout=15
        )

    if isinstance(response_message, dict) and "error" in response_message:
        return DoctorCheckResult("live-probe", "fail", f"Live model probe failed: {response_message['error']}")

    content = str(getattr(response_message, "content", "") or "").strip()
    usage_detail = ""
    if usage and usage.get("total_tokens") is not None:
        usage_detail = f" (total tokens: {usage.get('total_tokens')})"
    return DoctorCheckResult("live-probe", "pass", f"Model responded with: {content or '[empty response]'}{usage_detail}")


async def doctor(args: object, config: object) -> int:
    from app.cli.options import resolve_runtime_options
    from app.cli.ui import ConsoleUI

    options = resolve_runtime_options(args, config.defaults)
    ui = ConsoleUI(use_color=options.use_color, auto_approve=True)
    results = run_workspace_checks(options, config, args)

    if getattr(args, "live", False):
        credentials_status = next((r.status for r in results if r.name == "credentials"), "warn")
        workspace_status = next((r.status for r in results if r.name == "workspace"), "fail")
        if credentials_status == "fail" or workspace_status == "fail":
            results.append(DoctorCheckResult(
                "live-probe", "warn",
                "Live probe skipped because workspace or credentials checks failed.",
            ))
        else:
            results.append(await run_live_probe(options))

    pass_count = warn_count = fail_count = 0
    for result in results:
        render_doctor_result(ui, result)
        if result.status == "pass":
            pass_count += 1
        elif result.status == "warn":
            warn_count += 1
        else:
            fail_count += 1

    ui.print_line()
    if fail_count:
        ui.error(f"Doctor finished with {pass_count} passed, {warn_count} warnings, and {fail_count} failures.")
        return 1

    ui.success(f"Doctor finished with {pass_count} passed and {warn_count} warnings.")
    return 0
