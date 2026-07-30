"""`apsara mcp` — inspect the MCP servers configured for this workspace.

Answers the two questions people actually have when a server misbehaves: is it
configured the way I think, and does it actually connect?
"""
from pathlib import Path
from typing import Any

from apsara_cli.config import trust as trust_store
from apsara_cli.shared.ui import ConsoleUI, Theme


def _workspace_root(args: Any, config: Any) -> Path:
    hint = getattr(args, "workspace", None) or getattr(config.defaults, "workspace", None)
    if hint:
        return Path(hint).expanduser().resolve()
    return Path.cwd().resolve()


async def mcp_status(args: Any, config: Any) -> int:
    use_color = getattr(args, "color", None)
    theme = Theme()
    config_theme = getattr(config, "theme", None)
    if config_theme is not None:
        config_theme.apply_to(theme)
    ui = ConsoleUI(use_color=True if use_color is None else use_color, theme=theme)

    workspace = _workspace_root(args, config)
    servers = list(getattr(config, "mcp_servers", []) or [])
    errors = list(getattr(config, "mcp_errors", []) or [])

    ui.print_line()
    ui.print_line(
        f"  {ui.badge('mcp', '15', '48;2;70;85;115')}  "
        f"{ui.dim(str(config.path) if getattr(config, 'exists', False) else 'no config file')}"
    )
    ui.print_line()

    for message in errors:
        ui.error(message)
    if errors:
        ui.print_line()

    if not servers:
        ui.info("No MCP servers configured.")
        ui.print_line()
        ui.print_line(f"  {ui.dim('Add one to .apsara/config.toml:')}")
        ui.print_line()
        for line in (
            "[mcp_servers.filesystem]",
            'command = "npx"',
            'args = ["-y", "@modelcontextprotocol/server-filesystem", "."]',
        ):
            ui.print_line(f"    {ui.dim(line)}")
        ui.print_line()
        return 0

    trusted = trust_store.list_trusted(workspace)

    for server in servers:
        digest = trust_store.digest_text(server.trust_digest_source())
        entry = trusted.get(f"mcp:{server.name}")
        is_trusted = isinstance(entry, dict) and entry.get("sha256") == digest

        if not server.enabled:
            state, colour = "disabled", "38;2;150;155;165"
        elif is_trusted:
            state, colour = "trusted", "38;2;120;200;150"
        else:
            state, colour = "needs approval", "38;2;240;190;110"

        ui.print_line(
            f"  {ui.style('◆', colour)} {ui.style(server.name, '1', '38;2;220;225;240')}  "
            f"{ui.dim(server.transport)}  {ui.style(state, colour)}"
        )
        ui.print_line(f"      {ui.dim(server.describe())}")

        problem = server.validate()
        if problem:
            ui.print_line(f"      {ui.style('✗ ' + problem, '38;2;220;120;100')}")

    ui.print_line()

    if not getattr(args, "connect", True):
        return 0

    candidates = [s for s in servers if s.enabled and s.validate() is None]
    if not candidates:
        ui.warning("No servers are in a connectable state.")
        return 1

    # Connecting launches the server, so it goes through the same approval gate
    # as a chat session — a diagnostic command must not be the way around it.
    from apsara_cli.engine.tools import agent_runtime_context, request_workspace_trust

    connectable = []
    with agent_runtime_context(
        workspace_root=workspace,
        trust_callback=ui.confirm_action,
    ):
        for server in candidates:
            if request_workspace_trust(
                f"mcp:{server.name}",
                trust_store.digest_text(server.trust_digest_source()),
                {
                    "kind": "mcp",
                    "server": server.name,
                    "display_path": server.describe(),
                    "command_preview": server.describe(),
                },
            ):
                connectable.append(server)
            else:
                ui.warning(f"Skipped '{server.name}' — not approved.")

    if not connectable:
        return 1

    ui.info("Connecting…")
    ui.print_line()

    from apsara_cli.engine.mcp_client import McpManager

    manager = McpManager(connectable)
    failures = 0
    try:
        statuses = await manager.connect()
        for status in statuses:
            if status.connected:
                ui.success(
                    f"{status.name} — {status.tool_count} tool"
                    f"{'s' if status.tool_count != 1 else ''}"
                )
                for name in sorted(manager.tool_names()):
                    tool = manager.describe_tool(name)
                    if tool is not None and tool.server == status.name:
                        ui.print_line(f"      {ui.dim(name)}")
            else:
                failures += 1
                ui.error(f"{status.name} — {status.error}")
    finally:
        await manager.aclose()

    ui.print_line()
    return 1 if failures else 0
