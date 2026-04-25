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
        model_id="groq/llama-3.1-8b-instant",
        display_name="Llama 3.1 8B Instant",
        provider="groq",
        tier="free",
        context_window=128_000,
        env_var="GROQ_API_KEY",
        notes="Ultra-fast, lightweight tasks",
        aliases=["llama8b", "llama-8b", "llama-instant"],
    ),
    ModelEntry(
        model_id="groq/deepseek-r1-distill-llama-70b",
        display_name="DeepSeek R1 Distill 70B",
        provider="groq",
        tier="free",
        context_window=128_000,
        env_var="GROQ_API_KEY",
        notes="Reasoning model, free via Groq",
        aliases=["r1-groq", "deepseek-r1-groq"],
    ),
    ModelEntry(
        model_id="groq/gemma2-9b-it",
        display_name="Gemma 2 9B",
        provider="groq",
        tier="free",
        context_window=8_192,
        env_var="GROQ_API_KEY",
        notes="Google Gemma 2, fast and efficient",
        aliases=["gemma", "gemma2"],
    ),
    ModelEntry(
        model_id="groq/mixtral-8x7b-32768",
        display_name="Mixtral 8x7B",
        provider="groq",
        tier="free",
        context_window=32_768,
        env_var="GROQ_API_KEY",
        notes="Mixture-of-experts model via Groq",
        aliases=["mixtral"],
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
        model_id="gpt-4-turbo",
        display_name="GPT-4 Turbo",
        provider="openai",
        tier="paid",
        context_window=128_000,
        env_var="OPENAI_API_KEY",
        notes="GPT-4 Turbo with vision",
        aliases=["gpt4", "gpt-4"],
    ),
    ModelEntry(
        model_id="o1-mini",
        display_name="o1-mini",
        provider="openai",
        tier="paid",
        context_window=128_000,
        env_var="OPENAI_API_KEY",
        notes="OpenAI o1 reasoning model (fast)",
        aliases=["o1mini"],
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
        notes="Anthropic's best balanced model",
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
    ModelEntry(
        model_id="anthropic/claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        provider="anthropic",
        tier="paid",
        context_window=200_000,
        env_var="ANTHROPIC_API_KEY",
        notes="Most powerful Claude model",
        aliases=["opus", "claude-opus"],
    ),

    # ── Google Gemini (free quota + paid) ─────────────────────────────────────
    ModelEntry(
        model_id="gemini/gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        provider="google",
        tier="free",
        context_window=1_000_000,
        env_var="GEMINI_API_KEY",
        notes="Latest Gemini Flash, free quota available",
        aliases=["gemini-flash", "flash", "gemini2"],
    ),
    ModelEntry(
        model_id="gemini/gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        provider="google",
        tier="paid",
        context_window=2_000_000,
        env_var="GEMINI_API_KEY",
        notes="2M context window, advanced reasoning",
        aliases=["gemini-pro", "pro"],
    ),
    ModelEntry(
        model_id="gemini/gemini-1.5-flash",
        display_name="Gemini 1.5 Flash",
        provider="google",
        tier="paid",
        context_window=1_000_000,
        env_var="GEMINI_API_KEY",
        notes="Fast Gemini model, 1M context",
        aliases=["gemini1-flash"],
    ),

    # ── Mistral (paid but affordable) ─────────────────────────────────────────
    ModelEntry(
        model_id="mistral/mistral-large-latest",
        display_name="Mistral Large",
        provider="mistral",
        tier="paid",
        context_window=128_000,
        env_var="MISTRAL_API_KEY",
        notes="Mistral's flagship model",
        aliases=["mistral-large", "mistral"],
    ),
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
    ModelEntry(
        model_id="mistral/mistral-small-latest",
        display_name="Mistral Small",
        provider="mistral",
        tier="paid",
        context_window=128_000,
        env_var="MISTRAL_API_KEY",
        notes="Fast and affordable Mistral",
        aliases=["mistral-small"],
    ),

    # ── DeepSeek (very affordable) ────────────────────────────────────────────
    ModelEntry(
        model_id="deepseek/deepseek-chat",
        display_name="DeepSeek V3",
        provider="deepseek",
        tier="paid",
        context_window=64_000,
        env_var="DEEPSEEK_API_KEY",
        notes="High quality, very low cost",
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

    # ── xAI Grok (paid) ───────────────────────────────────────────────────────
    ModelEntry(
        model_id="xai/grok-beta",
        display_name="Grok Beta",
        provider="xai",
        tier="paid",
        context_window=131_072,
        env_var="XAI_API_KEY",
        notes="xAI Grok model",
        aliases=["grok"],
    ),

    # ── Cohere (paid) ─────────────────────────────────────────────────────────
    ModelEntry(
        model_id="cohere/command-r-plus",
        display_name="Command R+",
        provider="cohere",
        tier="paid",
        context_window=128_000,
        env_var="COHERE_API_KEY",
        notes="Cohere's most capable model",
        aliases=["command-r-plus", "cohere"],
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
    ModelEntry(
        model_id="ollama/deepseek-r1:7b",
        display_name="DeepSeek R1 7B (local)",
        provider="ollama",
        tier="local",
        context_window=64_000,
        env_var=None,
        notes="Local reasoning model via Ollama",
        aliases=["local-r1"],
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
