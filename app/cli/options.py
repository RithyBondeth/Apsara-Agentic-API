import argparse
import os
from pathlib import Path
from typing import Any, Optional, Set

from dotenv import dotenv_values

from app.cli.types import ResolvedOptions
from app.cli.ui import default_use_color


def resolve_workspace(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def resolve_value(explicit: Any, config_value: Any, fallback: Any) -> Any:
    if explicit is not None:
        return explicit
    if config_value is not None:
        return config_value
    return fallback


def parse_allowed_commands(raw_commands: Any) -> Optional[Set[str]]:
    if raw_commands is None:
        return None
    if isinstance(raw_commands, str):
        commands = {part.strip() for part in raw_commands.split(",") if part.strip()}
    elif isinstance(raw_commands, list):
        commands = {str(item).strip() for item in raw_commands if str(item).strip()}
    else:
        raise ValueError("Allowed commands must be a comma-separated string or a list.")

    if not commands:
        raise ValueError("Allowed commands cannot be empty when provided.")
    return commands


def resolve_runtime_options(args: argparse.Namespace, config_defaults: Any) -> ResolvedOptions:
    workspace = resolve_value(args.workspace, config_defaults.workspace, ".")
    model = resolve_value(args.model, config_defaults.model, "gpt-4o")
    session = resolve_value(args.session, config_defaults.session, "default")
    stateless = bool(resolve_value(args.stateless, config_defaults.stateless, False))
    allow_bash = bool(resolve_value(args.allow_bash, config_defaults.allow_bash, False))
    allowed_commands = parse_allowed_commands(
        resolve_value(args.allowed_commands, config_defaults.allowed_commands, None)
    )
    max_file_size = resolve_value(args.max_file_size, config_defaults.max_file_size, None)
    auto_approve = bool(resolve_value(args.auto_approve, config_defaults.auto_approve, False))
    use_color = bool(resolve_value(args.color, config_defaults.color, default_use_color()))

    return ResolvedOptions(
        workspace_root=resolve_workspace(str(workspace)),
        model=str(model),
        session=str(session),
        stateless=stateless,
        allow_bash=allow_bash,
        allowed_commands=allowed_commands,
        max_file_size=max_file_size,
        auto_approve=auto_approve,
        use_color=use_color,
    )


def load_cli_environment(args: argparse.Namespace, config: Any) -> list[Path]:
    workspace = resolve_value(getattr(args, "workspace", None), config.defaults.workspace, ".")
    candidates = [resolve_workspace(str(workspace)), Path.cwd().resolve()]

    loaded_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for base_path in candidates:
        env_path = base_path / ".env"
        if env_path in seen_paths or not env_path.exists():
            continue
        seen_paths.add(env_path)

        values = dotenv_values(env_path)
        loaded_any = False
        for key, value in values.items():
            if value is None or key in os.environ:
                continue
            os.environ[key] = value
            loaded_any = True

        if loaded_any:
            loaded_paths.append(env_path)

    return loaded_paths


def detect_model_credentials(model: str) -> tuple[str, Optional[list[str]], str]:
    raw_model = model.strip()
    provider = None
    model_name = raw_model

    if "/" in raw_model:
        provider, model_name = raw_model.split("/", 1)
        provider = provider.lower()
    normalized_name = model_name.lower()

    if provider in {"openai", "azure", "azure_openai"} or normalized_name.startswith(
        ("gpt-", "o1", "o3", "o4", "o5", "codex-", "text-embedding-")
    ):
        if provider in {"azure", "azure_openai"}:
            return ("azure-openai", ["AZURE_OPENAI_API_KEY", "AZURE_API_KEY"], "Azure OpenAI-style model detected.")
        return ("openai", ["OPENAI_API_KEY"], "OpenAI-style model detected.")

    if provider == "anthropic" or normalized_name.startswith("claude"):
        return ("anthropic", ["ANTHROPIC_API_KEY"], "Anthropic-style model detected.")

    if provider in {"gemini", "google"} or normalized_name.startswith("gemini"):
        return ("gemini", ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "Gemini-style model detected.")

    if provider == "groq":
        return ("groq", ["GROQ_API_KEY"], "Groq-style model detected.")

    if provider in {"together", "together_ai"}:
        return ("together", ["TOGETHER_API_KEY"], "Together-style model detected.")

    if provider == "mistral" or normalized_name.startswith("mistral"):
        return ("mistral", ["MISTRAL_API_KEY"], "Mistral-style model detected.")

    if provider == "xai":
        return ("xai", ["XAI_API_KEY"], "xAI-style model detected.")

    if provider == "deepseek" or normalized_name.startswith("deepseek"):
        return ("deepseek", ["DEEPSEEK_API_KEY"], "DeepSeek-style model detected.")

    if provider == "openrouter":
        return ("openrouter", ["OPENROUTER_API_KEY"], "OpenRouter-style model detected.")

    if provider in {"fireworks", "fireworks_ai"}:
        return ("fireworks", ["FIREWORKS_API_KEY"], "Fireworks-style model detected.")

    if provider == "cohere" or normalized_name.startswith("command"):
        return ("cohere", ["COHERE_API_KEY"], "Cohere-style model detected.")

    if provider == "cerebras":
        return ("cerebras", ["CEREBRAS_API_KEY"], "Cerebras-style model detected.")

    if provider == "bedrock":
        return ("bedrock", ["AWS_ACCESS_KEY_ID", "AWS_PROFILE"], "Bedrock-style model detected.")

    if provider == "vertex_ai":
        return ("vertex_ai", ["GOOGLE_APPLICATION_CREDENTIALS"], "Vertex AI-style model detected.")

    if provider == "ollama":
        return ("ollama", None, "Ollama-style local model detected; no API key required.")

    return ("unknown", None, f"Could not infer credentials for model '{model}'.")
