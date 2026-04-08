"""
KickForge Bot — chat bot framework with commands, loyalty, moderation & plugins.

Usage:
    from kickforge_bot import KickBot

    bot = KickBot(client_id="...", client_secret="...")

    @bot.command("!ping", cooldown=5)
    async def ping(ctx):
        await ctx.reply("pong!")

    bot.run(port=8420)
"""

from kickforge_bot.bot import KickBot
from kickforge_bot.commands.handler import CommandHandler, CommandContext, CommandDefinition
from kickforge_bot.loyalty import LoyaltyDB, UserStats
from kickforge_bot.moderation import ModerationConfig, ModerationEngine, ModerationAction
from kickforge_bot.timers import TimerManager
from kickforge_bot.polls import PollManager, Poll, Giveaway
from kickforge_bot.plugins.base import Plugin

__all__ = [
    "KickBot",
    "CommandHandler",
    "CommandContext",
    "CommandDefinition",
    "LoyaltyDB",
    "UserStats",
    "ModerationConfig",
    "ModerationEngine",
    "ModerationAction",
    "TimerManager",
    "PollManager",
    "Poll",
    "Giveaway",
    "Plugin",
]
