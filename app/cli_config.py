from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10+
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path.home() / ".apsara" / "config.toml"
LOCAL_CONFIG_DIRNAME = ".apsara"
LOCAL_CONFIG_FILENAME = "config.toml"


@dataclass
class CliDefaults:
    workspace: Optional[str] = None
    model: Optional[str] = None
    session: Optional[str] = None
    stateless: Optional[bool] = None
    allow_bash: Optional[bool] = None
    allowed_commands: Optional[list[str]] = None
    max_file_size: Optional[int] = None
    auto_approve: Optional[bool] = None
    color: Optional[bool] = None


@dataclass
class CliUi:
    welcome_title: Optional[str] = None
    welcome_subtitle: Optional[str] = None
    powered_by: Optional[str] = None
    welcome_animation: Optional[bool] = None
    welcome_frame_delay_ms: Optional[int] = None


@dataclass
class CliConfig:
    path: Path
    exists: bool
    defaults: CliDefaults
    ui: CliUi


def _optional_str(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Config field '{field_name}' must be a string.")
    return value


def _optional_bool(value: Any, field_name: str) -> Optional[bool]:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Config field '{field_name}' must be a boolean.")
    return value


def _optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Config field '{field_name}' must be an integer.")
    return value


def _optional_string_list(value: Any, field_name: str) -> Optional[list[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"Config field '{field_name}' must be a list of strings."
        )
    return value


def project_config_path(base_dir: Path) -> Path:
    return base_dir / LOCAL_CONFIG_DIRNAME / LOCAL_CONFIG_FILENAME


def find_project_config(start_dir: Path) -> Optional[Path]:
    current = start_dir.resolve()
    for candidate_dir in (current, *current.parents):
        candidate = project_config_path(candidate_dir)
        if candidate.exists():
            return candidate
    return None


def resolve_cli_config_path(
    config_path: Optional[str] = None,
    workspace_hint: Optional[str] = None,
) -> Path:
    if config_path:
        return Path(config_path).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if workspace_hint:
        workspace = Path(workspace_hint).expanduser()
        if not workspace.is_absolute():
            workspace = (cwd / workspace).resolve()
        else:
            workspace = workspace.resolve()
        workspace_config = find_project_config(workspace)
        if workspace_config is not None:
            return workspace_config

    cwd_config = find_project_config(cwd)
    if cwd_config is not None:
        return cwd_config

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    if workspace_hint:
        workspace = Path(workspace_hint).expanduser()
        if not workspace.is_absolute():
            workspace = (cwd / workspace).resolve()
        else:
            workspace = workspace.resolve()
        return project_config_path(workspace)

    return project_config_path(cwd)


def load_cli_config(
    config_path: Optional[str] = None,
    workspace_hint: Optional[str] = None,
) -> CliConfig:
    path = resolve_cli_config_path(config_path, workspace_hint)
    if not path.exists():
        return CliConfig(
            path=path,
            exists=False,
            defaults=CliDefaults(),
            ui=CliUi(),
        )

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    defaults_raw = parsed.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        raise ValueError("Config section 'defaults' must be a table.")
    ui_raw = parsed.get("ui", {})
    if not isinstance(ui_raw, dict):
        raise ValueError("Config section 'ui' must be a table.")

    defaults = CliDefaults(
        workspace=_optional_str(defaults_raw.get("workspace"), "defaults.workspace"),
        model=_optional_str(defaults_raw.get("model"), "defaults.model"),
        session=_optional_str(defaults_raw.get("session"), "defaults.session"),
        stateless=_optional_bool(defaults_raw.get("stateless"), "defaults.stateless"),
        allow_bash=_optional_bool(
            defaults_raw.get("allow_bash"), "defaults.allow_bash"
        ),
        allowed_commands=_optional_string_list(
            defaults_raw.get("allowed_commands"),
            "defaults.allowed_commands",
        ),
        max_file_size=_optional_int(
            defaults_raw.get("max_file_size"), "defaults.max_file_size"
        ),
        auto_approve=_optional_bool(
            defaults_raw.get("auto_approve"), "defaults.auto_approve"
        ),
        color=_optional_bool(defaults_raw.get("color"), "defaults.color"),
    )
    ui = CliUi(
        welcome_title=_optional_str(ui_raw.get("welcome_title"), "ui.welcome_title"),
        welcome_subtitle=_optional_str(
            ui_raw.get("welcome_subtitle"), "ui.welcome_subtitle"
        ),
        powered_by=_optional_str(ui_raw.get("powered_by"), "ui.powered_by"),
        welcome_animation=_optional_bool(
            ui_raw.get("welcome_animation"), "ui.welcome_animation"
        ),
        welcome_frame_delay_ms=_optional_int(
            ui_raw.get("welcome_frame_delay_ms"), "ui.welcome_frame_delay_ms"
        ),
    )

    return CliConfig(path=path, exists=True, defaults=defaults, ui=ui)
