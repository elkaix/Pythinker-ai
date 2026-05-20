"""``/pairing`` slash command — manage DM sender approval."""

from __future__ import annotations

from pythinker.bus.events import OutboundMessage
from pythinker.command.router import CommandContext
from pythinker.pairing import PAIRING_COMMAND_META_KEY, handle_pairing_command


async def cmd_pairing(ctx: CommandContext) -> OutboundMessage:
    """List, approve, deny or revoke pairing requests."""
    reply = handle_pairing_command(ctx.msg.channel, ctx.args)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=reply,
        metadata={PAIRING_COMMAND_META_KEY: True},
    )
