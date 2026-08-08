"""
Model registry for Apsara Agentic CLI.

Each entry describes a supported model: its LiteLLM model_id, display name,
provider, context window, pricing tier, required env var, and optional aliases
that users can type as shortcuts in /model <name>.

Tiers
  free  — provider offers a free tier (e.g. Groq, Gemini free quota)
  paid  — requires a paid API key
  local — runs locally via Ollama, no key needed
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_MODEL = "opencode/big-pickle"
OPENCODE_API_BASE = "https://opencode.ai/zen/v1"


@dataclass
class ModelEntry:
    model_id: str           # LiteLLM model string, e.g. "groq/llama-3.3-70b-versatile"
    display_name: str       # Human-friendly name shown in /models
    provider: str           # Grouping key, e.g. "groq", "openai"
    tier: str               # "free" | "paid" | "local"
    context_window: int     # Max tokens (input + output)
    env_var: Optional[str]  # Primary env var needed, None for local
    notes: str              # One-line description shown in /models
    aliases: list[str] = field(default_factory=list)  # Short names, e.g. ["sonnet"]


# ── Registry ──────────────────────────────────────────────────────────────────

MODELS: list[ModelEntry] = [
    # ── OpenCode Zen (free for a limited period) ─────────────────────────────
    ModelEntry(
        model_id=DEFAULT_MODEL,
        display_name="Big Pickle",
        provider="opencode",
        tier="free",
        context_window=200_000,
        env_var="OPENCODE_API_KEY",
        notes="Reasoning coding model; free temporarily (avoid confidential code)",
        aliases=["big-pickle", "pickle"],
    ),

    # ── Groq (free tier — fastest hosted inference) ───────────────────────────
    ModelEntry(
        model_id="groq/llama-3.3-70b-versatile",
        display_name="Llama 3.3 70B",
        provider="groq",
        tier="free",
        context_window=128_000,
        env_var="GROQ_API_KEY",
        notes="Fast, general-purpose — default model",
        aliases=["llama", "llama70b", "llama-70b"],
    ),
    ModelEntry(
        model_id="groq/deepseek-r1-distill-llama-70b",
        display_name="DeepSeek R1 Distill 70B",
        provider="groq",
        tier="free",
        context_window=128_000,
        env_var="GROQ_API_KEY",
        notes="Reasoning model, high speed via Groq",
        aliases=["r1-groq", "deepseek-r1-groq"],
    ),

    # ── OpenAI (paid) ─────────────────────────────────────────────────────────
    ModelEntry(
        model_id="gpt-4o",
        display_name="GPT-4o",
        provider="openai",
        tier="paid",
        context_window=128_000,
        env_var="OPENAI_API_KEY",
        notes="OpenAI flagship multimodal model",
        aliases=["4o"],
    ),
    ModelEntry(
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        provider="openai",
        tier="paid",
        context_window=128_000,
        env_var="OPENAI_API_KEY",
        notes="Affordable and fast GPT-4o",
        aliases=["4o-mini", "gpt-mini"],
    ),
    ModelEntry(
        model_id="o3-mini",
        display_name="o3-mini",
        provider="openai",
        tier="paid",
        context_window=200_000,
        env_var="OPENAI_API_KEY",
        notes="OpenAI o3 reasoning model",
        aliases=["o3mini", "o3"],
    ),

    # ── Anthropic (paid) ──────────────────────────────────────────────────────
    ModelEntry(
        model_id="anthropic/claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        provider="anthropic",
        tier="paid",
        context_window=200_000,
        env_var="ANTHROPIC_API_KEY",
        notes="Anthropic's best balanced model for coding",
        aliases=["sonnet", "claude-sonnet", "claude"],
    ),
    ModelEntry(
        model_id="anthropic/claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        provider="anthropic",
        tier="paid",
        context_window=200_000,
        env_var="ANTHROPIC_API_KEY",
        notes="Fast and affordable Claude",
        aliases=["haiku", "claude-haiku"],
    ),

    # ── Google Gemini (free quota + paid) ─────────────────────────────────────
    ModelEntry(
        model_id="gemini/gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        provider="google",
        tier="free",
        context_window=1_000_000,
        env_var="GEMINI_API_KEY",
        notes="Latest Gemini Flash, 1M context, free quota",
        aliases=["gemini-flash", "flash", "gemini2"],
    ),
    ModelEntry(
        model_id="gemini/gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        provider="google",
        tier="paid",
        context_window=2_000_000,
        env_var="GEMINI_API_KEY",
        notes="Massive 2M context window, advanced reasoning",
        aliases=["gemini-pro", "pro"],
    ),

    # ── Mistral (paid but affordable) ─────────────────────────────────────────
    ModelEntry(
        model_id="mistral/codestral-latest",
        display_name="Codestral",
        provider="mistral",
        tier="paid",
        context_window=256_000,
        env_var="MISTRAL_API_KEY",
        notes="Mistral's code-specialist model",
        aliases=["codestral"],
    ),

    # ── DeepSeek (very affordable) ────────────────────────────────────────────
    ModelEntry(
        model_id="deepseek/deepseek-chat",
        display_name="DeepSeek V3",
        provider="deepseek",
        tier="paid",
        context_window=64_000,
        env_var="DEEPSEEK_API_KEY",
        notes="High quality, extremely low cost",
        aliases=["deepseek", "deepseek-v3"],
    ),
    ModelEntry(
        model_id="deepseek/deepseek-reasoner",
        display_name="DeepSeek R1",
        provider="deepseek",
        tier="paid",
        context_window=64_000,
        env_var="DEEPSEEK_API_KEY",
        notes="DeepSeek reasoning model",
        aliases=["r1", "deepseek-r1"],
    ),

    # ── Ollama (local — no key required) ─────────────────────────────────────
    ModelEntry(
        model_id="ollama/llama3.2",
        display_name="Llama 3.2 (local)",
        provider="ollama",
        tier="local",
        context_window=128_000,
        env_var=None,
        notes="Runs locally via Ollama, no API key",
        aliases=["ollama-llama", "local-llama"],
    ),
    ModelEntry(
        model_id="ollama/qwen2.5-coder:7b",
        display_name="Qwen 2.5 Coder 7B (local)",
        provider="ollama",
        tier="local",
        context_window=32_000,
        env_var=None,
        notes="Code-specialist model, runs locally",
        aliases=["qwen-coder", "local-coder"],
    ),
]


# ── Look-up helpers ───────────────────────────────────────────────────────────

def _alias_map() -> dict[str, ModelEntry]:
    m: dict[str, ModelEntry] = {}
    for entry in MODELS:
        m[entry.model_id.lower()] = entry
        for alias in entry.aliases:
            m[alias.lower()] = entry
    return m


_ALIAS_MAP: dict[str, ModelEntry] | None = None


def lookup_model(name: str) -> Optional[ModelEntry]:
    """Return the ModelEntry for an exact model_id or any registered alias."""
    global _ALIAS_MAP
    if _ALIAS_MAP is None:
        _ALIAS_MAP = _alias_map()
    return _ALIAS_MAP.get(name.strip().lower())


def resolve_model_id(name: str) -> str:
    """
    If *name* is a registered alias, return the canonical model_id.
    Otherwise return *name* unchanged (allows arbitrary LiteLLM strings).
    """
    entry = lookup_model(name)
    return entry.model_id if entry else name


# ── Key hints ────────────────────────────────────────────────────────────────
# (env_var → (expected_prefix_or_None, human_description))

KEY_HINTS: dict[str, tuple[Optional[str], str]] = {
    "OPENCODE_API_KEY":  (None,      "OpenCode Zen API key — no fixed prefix"),
    "OPENAI_API_KEY":     ("sk-",     "OpenAI keys start with  sk-"),
    "ANTHROPIC_API_KEY":  ("sk-ant-", "Anthropic keys start with  sk-ant-"),
    "GROQ_API_KEY":       ("gsk_",    "Groq keys start with  gsk_"),
    "GEMINI_API_KEY":     ("AI",      "Google AI keys start with  AI"),
    "MISTRAL_API_KEY":    (None,      "Mistral API key — no fixed prefix"),
    "DEEPSEEK_API_KEY":   ("sk-",     "DeepSeek keys start with  sk-"),
}


def resolve_litellm_request(model: str) -> tuple[str, dict[str, str]]:
    """Return the LiteLLM model ID and provider-specific request options."""
    canonical_model = resolve_model_id(model)
    if canonical_model == DEFAULT_MODEL:
        options = {
            "api_base": os.environ.get("OPENCODE_API_BASE", OPENCODE_API_BASE),
        }
        api_key = os.environ.get("OPENCODE_API_KEY")
        if api_key:
            options["api_key"] = api_key
        return "openai/big-pickle", options
    return canonical_model, {}


def validate_key_format(env_var: str, value: str) -> tuple[bool, str]:
    """
    Returns (looks_valid, hint_message).
    Always True when no prefix pattern is known for this key.
    """
    hint = KEY_HINTS.get(env_var)
    if not hint or not hint[0]:
        return True, ""
    prefix, description = hint
    if not value.startswith(prefix):
        return False, f"Expected format: {description}"
    return True, description


def env_vars_with_providers() -> list[tuple[str, list[str]]]:
    """Return [(env_var, [provider, ...]), ...] for all unique env vars in MODELS."""
    seen: dict[str, list[str]] = {}
    for entry in MODELS:
        if entry.env_var:
            if entry.env_var not in seen:
                seen[entry.env_var] = []
            if entry.provider not in seen[entry.env_var]:
                seen[entry.env_var].append(entry.provider)
    return list(seen.items())


def is_key_available(entry: ModelEntry) -> bool:
    """True if the model's required env var is set (or no key is needed)."""
    if entry.env_var is None:
        return True
    return bool(os.environ.get(entry.env_var))


def format_context_window(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens // 1_000_000}M"
    if tokens >= 1_000:
        return f"{tokens // 1_000}k"
    return str(tokens)


def providers_in_order() -> list[str]:
    """Return provider names in the order they first appear in MODELS."""
    seen: list[str] = []
    for e in MODELS:
        if e.provider not in seen:
            seen.append(e.provider)
    return seen


def models_for_provider(provider: str) -> list[ModelEntry]:
    """Return all registered models belonging to *provider* (in registry order)."""
    return [e for e in MODELS if e.provider == provider]


def provider_env_var(provider: str) -> Optional[str]:
    """Primary API-key env var for *provider*, or None for local providers (e.g. ollama)."""
    models = models_for_provider(provider)
    return models[0].env_var if models else None


def default_model_for_provider(provider: str) -> Optional[str]:
    """The default (first-listed) model_id for *provider*, or None if unknown."""
    models = models_for_provider(provider)
    return models[0].model_id if models else None
