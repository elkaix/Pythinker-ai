"""``/sync`` and ``/pythinker-sync`` slash commands.

The implementation intentionally focuses on the local upstream-audit workflow from
``sync/audit.py`` and lightweight upstream commit inspection from the sibling clone.

It intentionally does not perform auto-porting itself; the result is a command-driven
helper surface for the broader workflow.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from pythinker.bus.events import OutboundMessage
from pythinker.command.router import CommandContext

_SYNC_HELP_TEXT = """Usage:
/sync               Run the upstream audit script.
/sync show <sha>    Show a specific upstream commit diff.
"""

_MAX_SHOW_OUTPUT = 12_000


def _run_sync_audit(workspace: Path) -> str:
    """Run ``sync/audit.py`` and return captured output."""
    script = workspace / "sync" / "audit.py"
    if not script.exists():
        return "Local sync audit script not found. Run this command from the project root."

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return f"Could not execute python for sync audit: {exc}"

    output = [p for p in (proc.stdout.strip(), proc.stderr.strip()) if p]
    if proc.returncode != 0:
        return (
            "Sync audit failed (exit {}): {}".format(
                proc.returncode,
                "\n".join(output),
            )
        )

    if not output:
        return "Sync audit completed with no output."

    return "\n".join(output)


def _run_sync_show(workspace: Path, sha: str) -> str:
    """Show a commit from the sibling upstream bare clone."""
    sha = sha.strip()
    if not sha:
        return "Usage: /sync show <sha>"

    upstream = workspace / "sync" / "upstream.git"
    if not upstream.exists():
        return (
            "Sibling upstream clone is not available yet. "
            "Run `/sync` once to initialize it."
        )

    try:
        proc = subprocess.run(
            ["git", "-C", str(upstream), "show", sha],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return f"Could not execute git for upstream show: {exc}"

    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown error"
        return f"Could not show commit {sha}: {stderr}"

    output = proc.stdout.strip()
    if len(output) > _MAX_SHOW_OUTPUT:
        output = f"{output[:_MAX_SHOW_OUTPUT]}\n\n... output truncated"

    return output or "No output returned for that SHA."


async def cmd_sync(ctx: CommandContext) -> OutboundMessage:
    """Run/inspect the local upstream sync workflow."""
    workspace = Path(getattr(ctx.loop, "workspace", "."))
    raw_args = (ctx.args or "").strip()

    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not raw_args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=await asyncio.to_thread(_run_sync_audit, workspace),
            metadata=metadata,
        )

    parts = raw_args.split(maxsplit=1)
    action = parts[0].lower()
    if action == "show":
        sha = parts[1] if len(parts) > 1 else ""
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=await asyncio.to_thread(_run_sync_show, workspace, sha),
            metadata=metadata,
        )

    if action in {"help", "-h", "--help"}:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=_SYNC_HELP_TEXT,
            metadata=metadata,
        )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=f"Unknown /sync subcommand.\n\n{_SYNC_HELP_TEXT}",
        metadata=metadata,
    )
