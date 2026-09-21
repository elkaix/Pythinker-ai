"""Optional onboard step — interactive CRUD for named model presets.

Adapts the upstream model-preset wizard (which lived in a hub-and-spoke menu)
to Pythinker's linear ``_WIZARD_STEPS`` flow: the step shows the current
preset list and offers add / edit / delete / done. Each preset writes through
to ``ctx.draft.model_presets``; ``Config.resolve_preset()`` (see
``pythinker/config/schema.py``) consumes them at provider construction time.

The step always returns ``StepResult(status="continue")`` so it never blocks
the wizard. Users can press ``Done`` at any time to skip the section.
"""

from __future__ import annotations

from pythinker.cli.onboard_types import StepResult, _WizardContext
from pythinker.config.schema import Config, ModelPresetConfig

_DONE_KEY = "__done__"
_ADD_KEY = "__add__"
_CANCEL_KEY = "__cancel__"
_RESERVED_PRESET_NAME = "default"


def _provider_choices() -> list[tuple[str, str, str]]:
    """Provider options: ``auto`` + every registered provider, sorted."""
    from pythinker.providers.registry import PROVIDERS

    options: list[tuple[str, str, str]] = [("auto", "auto", "match by model prefix")]
    for spec in sorted(PROVIDERS, key=lambda s: s.name):
        options.append((spec.name, spec.name, ""))
    return options


def _list_presets(presets: dict[str, ModelPresetConfig]) -> list[tuple[str, str, str]]:
    """Build the (id, display, hint) options for the preset list view."""
    options: list[tuple[str, str, str]] = [
        (_ADD_KEY, "[+] Add new preset", ""),
    ]
    for name, preset in sorted(presets.items()):
        options.append((name, name, f"{preset.model} ({preset.provider})"))
    options.append((_DONE_KEY, "Done", "Continue to the next step"))
    return options


def _prompt_int(label: str, default: int) -> int:
    """Re-prompt the user until a positive integer is entered. Falls back to the default on empty."""
    from pythinker.cli.onboard_views import clack

    while True:
        raw = clack.text(label, default=str(default)).strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            clack.print_status(f"! '{raw}' is not an integer")
            continue
        if value <= 0:
            clack.print_status("! value must be > 0")
            continue
        return value


def _prompt_float(label: str, default: float) -> float:
    from pythinker.cli.onboard_views import clack

    while True:
        raw = clack.text(label, default=str(default)).strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            clack.print_status(f"! '{raw}' is not a number")
            continue
        return value


def _edit_preset(
    preset: ModelPresetConfig, *, title: str
) -> ModelPresetConfig | None:
    """Run the field-by-field editor for one preset. Returns None on cancel."""
    from pythinker.cli.onboard_views import clack

    clack.note(title, ["Editing preset fields. Empty input keeps the current value."])

    model = clack.text("Model id:", default=preset.model).strip()
    if not model:
        clack.print_status("! model is required; cancelling")
        return None

    provider = clack.select(
        "Provider:",
        options=_provider_choices(),
        default=preset.provider,
        searchable=True,
    )

    max_tokens = _prompt_int("Max tokens:", preset.max_tokens)
    context_window = _prompt_int("Context window tokens:", preset.context_window_tokens)
    temperature = _prompt_float("Temperature:", preset.temperature)

    reasoning_default = preset.reasoning_effort or ""
    reasoning_raw = clack.text(
        "Reasoning effort (minimal/low/medium/high/xhigh — blank to clear):",
        default=reasoning_default,
    ).strip()
    reasoning_effort = reasoning_raw or None

    return ModelPresetConfig(
        model=model,
        provider=provider,
        max_tokens=max_tokens,
        context_window_tokens=context_window,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )


def _add_preset(config: Config) -> None:
    from pythinker.cli.onboard_views import clack

    while True:
        name = clack.text("Preset name:", default="").strip()
        if not name:
            clack.print_status("! name cannot be empty")
            return
        if name == _RESERVED_PRESET_NAME:
            clack.print_status(
                "! 'default' is reserved (auto-generated from agents.defaults)"
            )
            continue
        if name in config.model_presets:
            clack.print_status(f"! preset '{name}' already exists")
            continue
        break

    seed = ModelPresetConfig(model="")
    updated = _edit_preset(seed, title=f"New preset: {name}")
    if updated is None:
        return
    config.model_presets[name] = updated
    clack.print_status(f"+ added preset '{name}'")


def _edit_existing(config: Config, name: str) -> None:
    from pythinker.cli.onboard_views import clack

    preset = config.model_presets.get(name)
    if preset is None:
        return

    action_options: list[tuple[str, str, str]] = [
        ("edit", "Edit", "Modify this preset's fields"),
    ]
    if name != _RESERVED_PRESET_NAME:
        action_options.append(("delete", "Delete", "Remove this preset"))
    action_options.append((_CANCEL_KEY, "Cancel", "Return to the preset list"))

    action = clack.select(f"Preset: {name}", options=action_options, default="edit")
    if action == _CANCEL_KEY:
        return

    if action == "delete":
        confirm = clack.confirm(f"Delete preset '{name}'?", default=False)
        if confirm:
            del config.model_presets[name]
            # If the active preset pointer references the just-deleted name,
            # clear it so Config validation does not raise on the next save.
            if config.agents.defaults.model_preset == name:
                config.agents.defaults.model_preset = None
            clack.print_status(f"- deleted preset '{name}'")
        return

    if action == "edit":
        updated = _edit_preset(preset, title=f"Edit preset: {name}")
        if updated is not None:
            config.model_presets[name] = updated
            clack.print_status(f"* updated preset '{name}'")


def _step_model_presets(ctx: _WizardContext) -> StepResult:
    """Optional CRUD for ``config.model_presets``.

    Skipped when the wizard is running non-interactively or under the
    QuickStart flow — the user can return to the section by re-running
    ``pythinker-ai onboard`` later.
    """
    from pythinker.cli import onboard as _onboard
    from pythinker.cli.onboard_views import clack

    if ctx.non_interactive or ctx.flow == "quickstart":
        return StepResult(status="skip")

    has_presets = bool(ctx.draft.model_presets)
    open_section = clack.confirm(
        "Define named model presets now? (Skip if not using presets)",
        default=has_presets,
    )
    if not open_section:
        return StepResult(status="continue")

    while True:
        options = _list_presets(ctx.draft.model_presets)
        picked = clack.select("Model presets", options=options, default=_DONE_KEY)
        if picked == _DONE_KEY:
            break
        if picked == _ADD_KEY:
            _add_preset(ctx.draft)
            continue
        _edit_existing(ctx.draft, picked)

    _onboard._emit_docs_link("model")
    return StepResult(status="continue")
