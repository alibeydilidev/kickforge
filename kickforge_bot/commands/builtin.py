"""
Built-in commands: !help, !uptime, !followage.

These are automatically registered when a KickBot starts.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from kickforge_bot.commands.handler import CommandHandler, CommandContext

if TYPE_CHECKING:
    from kickforge_bot.bot import KickBot


def register_builtins(handler: CommandHandler, bot: KickBot) -> None:
    """Register all built-in commands on the given handler."""

    @handler.command("help", description="List available commands")
    async def help_cmd(ctx: CommandContext) -> None:
        commands = handler.get_commands()
        lines = []
        for name, cmd in sorted(commands.items()):
            desc = cmd.description or "No description"
            lines.append(f"!{name} — {desc}")
        if lines:
            await ctx.reply(" | ".join(lines))
        else:
            await ctx.reply("No commands registered.")

    @handler.command("uptime", description="Show how long the bot has been running")
    async def uptime_cmd(ctx: CommandContext) -> None:
        elapsed = time.time() - bot._start_time
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            await ctx.reply(f"Uptime: {hours}h {minutes}m {seconds}s")
        elif minutes > 0:
            await ctx.reply(f"Uptime: {minutes}m {seconds}s")
        else:
            await ctx.reply(f"Uptime: {seconds}s")

    @handler.command("followage", description="Check when you followed")
    async def followage_cmd(ctx: CommandContext) -> None:
        await ctx.reply(
            f"@{ctx.sender.username}, follow age tracking requires Kick API integration."
        )
