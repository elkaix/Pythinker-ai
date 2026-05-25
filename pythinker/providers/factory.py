"""Create LLM providers from config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pythinker.config.schema import Config, InlineFallbackConfig, ModelPresetConfig
from pythinker.providers.base import GenerationSettings, LLMProvider
from pythinker.providers.fallback_provider import FallbackProvider
from pythinker.providers.registry import find_by_name


@dataclass(frozen=True)
class ProviderSnapshot:
    """A constructed provider plus the inputs it was built from.

    `signature` is the tuple of config fields that affect provider identity;
    callers can compare two snapshots' signatures to decide whether a hot
    reload is needed.
    """

    provider: LLMProvider
    model: str
    context_window_tokens: int | None
    signature: tuple[object, ...]


def _make_provider_core(
    config: Config,
    *,
    preset: ModelPresetConfig | None = None,
) -> LLMProvider:
    """Build a single plain ``LLMProvider`` from *preset* (or the default preset).

    No failover wrapping; used both for the primary provider and to construct
    fallback providers on demand inside :class:`FallbackProvider`.
    """
    resolved = preset if preset is not None else config.resolve_preset()
    model = resolved.model
    provider_name = config.get_provider_name(model, preset=resolved)
    p = config.get_provider(model, preset=resolved)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    # --- validation ---
    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from pythinker.providers.openai_codex_provider import OpenAICodexProvider

        provider: LLMProvider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from pythinker.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif backend == "github_copilot":
        from pythinker.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "anthropic":
        from pythinker.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, preset=resolved),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from pythinker.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, preset=resolved),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
            extra_body=p.extra_body if p else None,
            api_type=p.api_type if p and provider_name == "openai" else "auto",
        )

    provider.generation = GenerationSettings(
        temperature=resolved.temperature,
        max_tokens=resolved.max_tokens,
        reasoning_effort=resolved.reasoning_effort,
    )
    return provider


def _inline_fallback_preset(
    primary: ModelPresetConfig,
    fallback: InlineFallbackConfig,
) -> ModelPresetConfig:
    """Promote an inline fallback entry to a full ``ModelPresetConfig``.

    Missing fields inherit from the primary preset, except ``reasoning_effort``
    which is independent — an inline fallback that omits it disables reasoning
    for that fallback rather than inheriting the primary's value.
    """
    return ModelPresetConfig(
        model=fallback.model,
        provider=fallback.provider,
        max_tokens=fallback.max_tokens if fallback.max_tokens is not None else primary.max_tokens,
        context_window_tokens=(
            fallback.context_window_tokens
            if fallback.context_window_tokens is not None
            else primary.context_window_tokens
        ),
        temperature=(
            fallback.temperature if fallback.temperature is not None else primary.temperature
        ),
        reasoning_effort=fallback.reasoning_effort,
    )


def _resolve_fallback_presets(
    config: Config, primary: ModelPresetConfig
) -> list[ModelPresetConfig]:
    """Resolve ``agents.defaults.fallback_models`` into a list of presets."""
    presets: list[ModelPresetConfig] = []
    for fallback in config.agents.defaults.fallback_models:
        if isinstance(fallback, str):
            presets.append(config.model_presets[fallback])
        else:
            presets.append(_inline_fallback_preset(primary, fallback))
    return presets


def make_provider(config: Config) -> LLMProvider:
    """Create the LLM provider implied by config.

    Routing is driven by `ProviderSpec.backend` in the registry. Errors during
    validation (missing key, missing Azure base) raise `ValueError` so callers
    can decide how to surface them — the CLI translates these into
    `console.print` + `typer.Exit(1)`; the SDK lets them propagate.

    If ``agents.defaults.model_preset`` is set, the preset's model/provider/
    generation params take precedence over the inline ``defaults`` fields.

    When ``agents.defaults.fallback_models`` is non-empty, the primary provider
    is wrapped in :class:`FallbackProvider` so transient errors transparently
    fail over to fallback models in order.
    """
    primary_preset = config.resolve_preset()
    primary = _make_provider_core(config, preset=primary_preset)
    fallback_presets = _resolve_fallback_presets(config, primary_preset)

    if not fallback_presets:
        return primary

    return FallbackProvider(
        primary=primary,
        fallback_presets=fallback_presets,
        provider_factory=lambda fb: _make_provider_core(config, preset=fb),
    )


def _preset_signature(
    config: Config, preset: ModelPresetConfig
) -> tuple[object, ...]:
    """Identity tuple for a single preset (primary or fallback)."""
    model = preset.model
    p = config.get_provider(model, preset=preset)
    extra_body_sig = (
        json.dumps(p.extra_body, sort_keys=True) if p and p.extra_body else None
    )
    extra_headers_sig = (
        json.dumps(sorted(p.extra_headers.items())) if p and p.extra_headers else None
    )
    return (
        model,
        preset.provider,
        config.get_provider_name(model, preset=preset),
        config.get_api_key(model, preset=preset),
        config.get_api_base(model, preset=preset),
        preset.max_tokens,
        preset.temperature,
        preset.reasoning_effort,
        preset.context_window_tokens,
        extra_body_sig,
        extra_headers_sig,
        p.api_type if p else "auto",
    )


def provider_signature(config: Config) -> tuple[object, ...]:
    """Return the config fields that determine provider identity.

    Compare two signatures to detect whether `make_provider` would produce a
    different provider — useful for hot-reload paths that want to skip
    rebuilding when nothing material changed.
    """
    preset = config.resolve_preset()
    fallback_presets = _resolve_fallback_presets(config, preset)
    return (
        config.agents.defaults.model_preset or "default",
        _preset_signature(config, preset),
        tuple(_preset_signature(config, fb) for fb in fallback_presets),
    )


def build_provider_snapshot(config: Config) -> ProviderSnapshot:
    """Build a snapshot capturing both the provider and the inputs that made it.

    When fallback models are configured, the snapshot's
    ``context_window_tokens`` is the smallest window across primary + fallbacks
    so token-budget callers don't overshoot the most restrictive model.
    """
    preset = config.resolve_preset()
    fallback_presets = _resolve_fallback_presets(config, preset)
    windows: list[int | None] = [preset.context_window_tokens]
    for fb in fallback_presets:
        windows.append(fb.context_window_tokens)
    defined = [w for w in windows if w is not None]
    smallest = min(defined) if defined else None
    return ProviderSnapshot(
        provider=make_provider(config),
        model=preset.model,
        context_window_tokens=smallest,
        signature=provider_signature(config),
    )


def load_provider_snapshot(config_path: Path | None = None) -> ProviderSnapshot:
    """Convenience: load+resolve config from disk and build a snapshot."""
    from pythinker.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(resolve_config_env_vars(load_config(config_path)))
