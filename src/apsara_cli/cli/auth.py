"""Local credential store for bring-your-own-key (BYO-key) providers.

Apsara is standalone: users pick a model provider and supply their own API key.
Keys are stored per-provider in ~/.apsara/credentials.json (owner-only, chmod 600)
and injected into the environment at startup so LiteLLM can read them.

Stored file shape:
    {
      "active_provider": "openai",
      "providers": {
        "openai": {"api_key": "sk-...", "default_model": "gpt-4o"},
        "ollama": {"default_model": "ollama/llama3.2", "local": true}
      }
    }
"""
import json
import os
from pathlib import Path
from typing import Optional

CREDENTIALS_PATH = Path.home() / ".apsara" / "credentials.json"


def load_credentials() -> dict:
    """Return the parsed credentials file, or an empty dict if missing/corrupt."""
    if not CREDENTIALS_PATH.exists():
        return {}
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_credentials(data: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Owner read/write only — this file holds secrets.
    CREDENTIALS_PATH.chmod(0o600)


def save_provider_key(
    provider: str,
    api_key: Optional[str] = None,
    default_model: Optional[str] = None,
) -> None:
    """Store (or update) a provider's API key and default model, and make it active.

    For local providers (e.g. ollama) `api_key` may be omitted.
    """
    data = load_credentials()
    providers = data.setdefault("providers", {})
    entry = providers.setdefault(provider, {})
    if api_key:
        entry["api_key"] = api_key
    else:
        entry["local"] = True
    if default_model:
        entry["default_model"] = default_model
    data["active_provider"] = provider
    _write_credentials(data)


def get_provider_key(provider: str) -> Optional[str]:
    return load_credentials().get("providers", {}).get(provider, {}).get("api_key")


def stored_providers() -> list[str]:
    return list(load_credentials().get("providers", {}).keys())


def get_active_provider() -> Optional[str]:
    return load_credentials().get("active_provider")


def get_active_default_model() -> Optional[str]:
    """Return the default model for the active provider, if one is configured."""
    data = load_credentials()
    provider = data.get("active_provider")
    if not provider:
        return None
    return data.get("providers", {}).get(provider, {}).get("default_model")


def set_active_provider(provider: str) -> bool:
    """Mark an already-stored provider as active. Returns False if not stored."""
    data = load_credentials()
    if provider not in data.get("providers", {}):
        return False
    data["active_provider"] = provider
    _write_credentials(data)
    return True


def remove_provider_key(provider: str) -> bool:
    """Remove one provider from the store. Returns False if it wasn't stored.

    If the removed provider was active, the active pointer moves to another
    stored provider (or clears when none remain).
    """
    data = load_credentials()
    providers = data.get("providers", {})
    if provider not in providers:
        return False
    del providers[provider]
    if data.get("active_provider") == provider:
        remaining = list(providers.keys())
        if remaining:
            data["active_provider"] = remaining[0]
        else:
            data.pop("active_provider", None)
    _write_credentials(data)
    return True


def clear_credentials() -> None:
    """Remove all stored provider credentials."""
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


def apply_credentials_to_env() -> None:
    """Inject stored provider API keys into os.environ.

    Existing environment variables (e.g. from a shell export or .env) win, so this
    only fills in keys that aren't already set.
    """
    from apsara_cli.engine.models import provider_env_var

    data = load_credentials()
    for provider, entry in data.get("providers", {}).items():
        env_var = provider_env_var(provider)
        api_key = entry.get("api_key")
        if env_var and api_key and not os.environ.get(env_var):
            os.environ[env_var] = api_key


def credentials_present_for_model(model: str) -> bool:
    """True if the API key required to call *model* is available in the environment.

    Local models (ollama) and models whose provider can't be inferred are treated
    as available — we let LiteLLM surface any real error rather than block early.
    """
    from apsara_cli.cli.options import detect_model_credentials

    apply_credentials_to_env()
    _provider, env_vars, _note = detect_model_credentials(model)
    if not env_vars:
        return True
    return any(os.environ.get(var) for var in env_vars)


def is_authenticated() -> bool:
    """Back-compat helper: True if any provider key is configured or present in env."""
    apply_credentials_to_env()
    if stored_providers():
        return True
    from apsara_cli.engine.models import env_vars_with_providers

    return any(os.environ.get(var) for var, _providers in env_vars_with_providers())
