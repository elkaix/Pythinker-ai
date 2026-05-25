"""Phase 2 smoke: drive a real provider, capture live ``file_activity`` events.

Asks the configured default provider to ``write_file`` ~80 lines into a temp
workspace and prints every emitted ``file_activity`` payload as it arrives.
Success looks like:

  • One or more frames with ``phase=start`` and ``approximate=true`` whose
    ``added`` count climbs monotonically (the StreamingFileEditTracker
    converting tool-call argument deltas into chip updates).
  • A final frame with ``phase=end`` and ``approximate=false`` carrying the
    exact line diff from the post-tool file snapshot.
  • No ``phase=start`` event with ``approximate=false`` between the live
    events and the final end — that would reset chip counts to zero on the
    WebUI.

Usage::

    uv run python scripts/smoke_phase2_streaming_chips.py

Requires the local pythinker-ai config to have a working provider (the script
uses whatever ``agents.defaults`` resolves to). Reads no secrets; writes
events to stdout only. Safe to run repeatedly.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from pythinker.agent.hook import AgentHook
from pythinker.agent.runner import AgentRunner, AgentRunSpec
from pythinker.agent.tools.filesystem import WriteFileTool
from pythinker.agent.tools.registry import ToolRegistry
from pythinker.config.loader import load_config
from pythinker.providers.factory import make_provider


class _StreamingHook(AgentHook):
    """Forces the runner into the streaming code path."""

    def wants_streaming(self) -> bool:
        return True


PROMPT = (
    "Use the write_file tool to create a file named smoke.py at the workspace "
    "root. The file must contain at least 70 distinct lines of valid Python "
    "code — a simple module that defines a class named Smoke with one short "
    "method per line of trivial repetitive logic. Do not output the code in "
    "the chat; only call the tool. After the tool call completes, reply with "
    "the single word 'done'."
)


async def main() -> int:
    config = load_config()
    override = os.environ.get("PYTHINKER_AI_SMOKE_MODEL")
    if override:
        config.agents.defaults.model = override
        # Drop any preset that would shadow the override.
        config.agents.defaults.model_preset = None  # type: ignore[assignment]
    provider = make_provider(config)
    print(f"[smoke] provider = {type(provider).__name__}")
    print(f"[smoke] model    = {config.agents.defaults.model}")

    with tempfile.TemporaryDirectory(prefix="pyhsmoke-") as td:
        workspace = Path(td)
        tools = ToolRegistry()
        tools.register(WriteFileTool(workspace=workspace))

        captured: list[tuple[float, dict[str, Any]]] = []
        t0 = time.monotonic()

        async def on_event(payload: dict[str, Any]) -> None:
            captured.append((time.monotonic() - t0, payload))
            print(
                f"[+{time.monotonic() - t0:5.2f}s] "
                f"{payload['phase']:<5}  "
                f"approx={'T' if payload.get('approximate') else 'F'}  "
                f"added={payload.get('added', 0):3d} "
                f"deleted={payload.get('deleted', 0):3d}  "
                f"call={payload['call_id'][:24]:24}  "
                f"path={payload.get('path') or '(unknown)'}"
            )

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": PROMPT}],
            tools=tools,
            model=config.agents.defaults.model,
            workspace=workspace,
            file_activity_callback=on_event,
            hook=_StreamingHook(),
            max_iterations=4,
            max_tool_result_chars=4096,
        ))

        print()
        print(f"[smoke] final content (truncated): {(result.final_content or '')[:80]!r}")
        smoke = workspace / "smoke.py"
        if smoke.exists():
            line_count = sum(1 for _ in smoke.open())
            print(f"[smoke] smoke.py wrote {line_count} lines on disk")
        else:
            print("[smoke] WARNING smoke.py was not created")

        # --- analysis ---
        live = [p for _, p in captured if p["phase"] == "start" and p.get("approximate")]
        sync_starts = [
            p for _, p in captured
            if p["phase"] == "start" and not p.get("approximate")
        ]
        ends = [p for _, p in captured if p["phase"] == "end"]

        print()
        print("[smoke] summary:")
        print(f"   total events       : {len(captured)}")
        print(f"   live (approx) start: {len(live)}")
        print(f"   sync (exact) start : {len(sync_starts)}  (should be 0)")
        print(f"   end events         : {len(ends)}")
        if live:
            adds = [p["added"] for p in live]
            print(f"   live 'added' walk  : {adds[:8]}{' …' if len(adds) > 8 else ''} → {adds[-1]}")

        # --- verdict ---
        verdict = []
        if not live:
            verdict.append("FAIL: no live (approximate) events fired")
        if sync_starts:
            verdict.append(
                f"FAIL: {len(sync_starts)} non-approximate start(s) leaked — "
                "would zero the chip counts"
            )
        if not ends:
            verdict.append("FAIL: no end event captured")
        elif ends[0].get("approximate"):
            verdict.append("FAIL: end event still marked approximate")

        # Whether the API actually streamed argument deltas (vs. dumping the
        # whole arg payload at output_item.done time). OpenAI Responses API
        # does the latter for tool calls; the tracker is wired correctly but
        # has no deltas to animate.
        live_added = [p["added"] for p in live if p.get("added", 0) > 0]
        animated = len(live_added) > 0 or len(live) > 2

        print()
        if verdict:
            for v in verdict:
                print(f"  ✗ {v}")
            return 1
        if animated:
            print("  ✓ chip animation path verified end-to-end (deltas streamed)")
        else:
            print(
                "  ~ chip wiring verified end-to-end, but the provider did "
                "not stream argument deltas (so the live 'added' counter did "
                "not climb; the chip will show 'writing… <path>' until done). "
                "This is expected for the OpenAI Responses API; chat.completions "
                "providers (Anthropic / OpenAI / DeepSeek / etc.) animate."
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
