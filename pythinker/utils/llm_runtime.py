"""Small helpers for passing the active LLM provider/model together.

Long-running background tasks (heartbeat, cron, dream) capture provider+model
at construction time. If the agent later swaps provider via /restart or
config reload, those tasks keep using stale references. This helper lets
callers pass a resolver instead, so each turn pulls the current runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pythinker.providers.base import LLMProvider


@dataclass(frozen=True)
class LLMRuntime:
    """Snapshot of the active LLM at a single point in time."""

    provider: "LLMProvider"
    model: str


LLMRuntimeResolver = Callable[[], LLMRuntime]


def static_llm_runtime(provider: "LLMProvider", model: str) -> LLMRuntimeResolver:
    """Resolver that always returns the same (provider, model) snapshot."""
    runtime = LLMRuntime(provider=provider, model=model)
    return lambda: runtime
