"""
KickBot — extends KickApp with command handling, loyalty, moderation,
timed messages, polls, and a plugin system.

Usage:
    from kickforge_bot import KickBot

    bot = KickBot(client_id="...", client_secret="...")

    @bot.command("!ping", cooldown=5)
    async def ping(ctx):
        await ctx.reply("pong!")

    bot.run(port=8420)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Coroutine, Optional

from kickforge_core.app import KickApp
from kickforge_core.events import (
    ChatMessageEvent,
    FollowEvent,
    GiftEvent,
    SubscriptionEvent,
)
from kickforge_bot.commands.handler import CommandHandler, CommandContext
from kickforge_bot.commands.builtin import register_builtins
from kickforge_bot.loyalty import LoyaltyDB, XP_PER_SUB
from kickforge_bot.moderation import ModerationConfig, ModerationEngine
from kickforge_bot.timers import TimerManager
from kickforge_bot.polls import PollManager
from kickforge_bot.plugins.base import Plugin

logger = logging.getLogger("kickforge.bot")


class KickBot(KickApp):
    """
    Full-featured Kick chat bot built on top of KickApp.

    Adds:
    - Command system (@bot.command decorator)
    - Loyalty / XP tracking (SQLite)
    - Auto-moderation (blacklist, caps, spam, links)
    - Timed messages
    - Polls and giveaways
    - Plugin system
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        prefix: str = "!",
        db_path: str = "loyalty.db",
        moderation: Optional[ModerationConfig] = None,
        mode: str = "websocket",
        webhook_path: str = "/webhook",
        verify_signatures: bool = True,
        log_level: str = "INFO",
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            mode=mode,
            webhook_path=webhook_path,
            verify_signatures=verify_signatures,
            log_level=log_level,
        )

        self._start_time = time.time()

        # Command system
        self.commands = CommandHandler(prefix=prefix)
        register_builtins(self.commands, self)

        # Loyalty
        self.loyalty = LoyaltyDB(db_path=db_path)
        self._loyalty_enabled = True

        # Moderation
        self.moderation = ModerationEngine(moderation or ModerationConfig())

        # Timers
        self.timers = TimerManager(
            send_func=self._timer_send,
            is_live_func=None,
        )

        # Polls
        self.polls = PollManager()

        # Plugins
        self._plugins: list[Plugin] = []

        # Register internal event handlers
        self._register_internal_handlers()

        logger.info("KickBot initialized (prefix=%s)", prefix)

    # -----------------------------------------------------------------------
    # Decorator: @bot.command(...)
    # -----------------------------------------------------------------------

    def command(
        self,
        name: str,
        cooldown: float = 0.0,
        permission: str = "everyone",
        description: str = "",
    ) -> Callable:
        """Decorator to register a bot command."""
        return self.commands.command(
            name=name,
            cooldown=cooldown,
            permission=permission,
            description=description,
        )

    # -----------------------------------------------------------------------
    # Plugin system
    # -----------------------------------------------------------------------

    async def load_plugin(self, plugin: Plugin) -> None:
        """Load a plugin into the bot."""
        self._plugins.append(plugin)
        await plugin.on_load(self)
        logger.info("Plugin loaded: %s", plugin.name)

    async def unload_plugin(self, plugin: Plugin) -> None:
        """Unload a plugin from the bot."""
        if plugin in self._plugins:
            await plugin.on_unload(self)
            self._plugins.remove(plugin)
            logger.info("Plugin unloaded: %s", plugin.name)

    # -----------------------------------------------------------------------
    # Config loading
    # -----------------------------------------------------------------------

    def load_config(self, config: dict[str, Any]) -> None:
        """
        Load bot configuration from a dict (typically parsed from YAML).

        Expected structure:
            bot:
              prefix: "!"
              moderation: { ... }
              timed_messages: [ { message, interval }, ... ]
              loyalty: { enabled: true, db_path: "loyalty.db" }
        """
        bot_cfg = config.get("bot", {})

        # Moderation
        mod_cfg = bot_cfg.get("moderation")
        if mod_cfg:
            self.moderation.update_config(ModerationConfig.from_dict(mod_cfg))

        # Timed messages
        timers_cfg = bot_cfg.get("timed_messages")
        if timers_cfg:
            self.timers.load_from_config(timers_cfg)

        # Loyalty toggle
        loyalty_cfg = bot_cfg.get("loyalty", {})
        self._loyalty_enabled = loyalty_cfg.get("enabled", True)

    # -----------------------------------------------------------------------
    # Internal handlers
    # -----------------------------------------------------------------------

    def _register_internal_handlers(self) -> None:
        """Wire up event bus to bot subsystems."""

        @self.bus.on("chat.message.sent")
        async def _on_chat(event: ChatMessageEvent) -> None:
            sender = event.sender
            if not sender:
                return

            # 1) Moderation check
            action = self.moderation.check(event)
            if action.action == "warn":
                msg = self.moderation.config.warn_message.format(username=sender.username)
                await self._send_to_channel(event.broadcaster_user_id, msg)
                return
            elif action.action == "timeout":
                try:
                    await self.api.ban_user(
                        broadcaster_id=event.broadcaster_user_id or 0,
                        user_id=sender.user_id,
                        duration=action.duration,
                        reason=action.reason,
                    )
                except Exception:
                    logger.exception("Failed to timeout user %s", sender.username)
                return
            elif action.action == "ban":
                try:
                    await self.api.ban_user(
                        broadcaster_id=event.broadcaster_user_id or 0,
                        user_id=sender.user_id,
                        reason=action.reason,
                    )
                except Exception:
                    logger.exception("Failed to ban user %s", sender.username)
                return

            # 2) Loyalty XP (before commands, so every message counts)
            if self._loyalty_enabled:
                try:
                    self.loyalty.add_message(sender.user_id, sender.username)
                except Exception:
                    logger.exception("Loyalty XP error")

            # 3) Command dispatch
            handled = await self.commands.process(event, self._command_send)
            if handled:
                return

            # 4) Giveaway keyword check
            giveaway = self.polls.active_giveaway
            if giveaway and event.message.strip().lower() == giveaway.keyword.lower():
                self.polls.enter_giveaway(sender.user_id, sender.username)

            # 5) Plugin hooks
            for plugin in self._plugins:
                try:
                    await plugin.on_message(event)
                except Exception:
                    logger.exception("Plugin %s.on_message raised", plugin.name)

        @self.bus.on("channel.followed")
        async def _on_follow(event: FollowEvent) -> None:
            for plugin in self._plugins:
                try:
                    await plugin.on_follow(event)
                except Exception:
                    logger.exception("Plugin %s.on_follow raised", plugin.name)

        @self.bus.on("kicks.gifted")
        async def _on_gift(event: GiftEvent) -> None:
            # Loyalty XP for gifts
            if self._loyalty_enabled and event.gifter_user_id:
                try:
                    self.loyalty.add_xp(
                        event.gifter_user_id,
                        event.gifter_username,
                        event.kicks_amount,
                    )
                except Exception:
                    logger.exception("Loyalty gift XP error")

            for plugin in self._plugins:
                try:
                    await plugin.on_gift(event)
                except Exception:
                    logger.exception("Plugin %s.on_gift raised", plugin.name)

        @self.bus.on("channel.subscription.new")
        async def _on_sub(event: SubscriptionEvent) -> None:
            if self._loyalty_enabled and event.subscriber_user_id:
                try:
                    self.loyalty.add_xp(
                        event.subscriber_user_id,
                        event.subscriber_username,
                        XP_PER_SUB,
                    )
                except Exception:
                    logger.exception("Loyalty sub XP error")

            for plugin in self._plugins:
                try:
                    await plugin.on_sub(event)
                except Exception:
                    logger.exception("Plugin %s.on_sub raised", plugin.name)

    # -----------------------------------------------------------------------
    # Send helpers
    # -----------------------------------------------------------------------

    async def _command_send(
        self,
        broadcaster_id: int,
        content: str,
        reply_to: Optional[str] = None,
    ) -> None:
        """Send function passed to CommandContext."""
        await self.api.send_message(
            broadcaster_id=broadcaster_id,
            content=content,
            reply_to=reply_to,
        )

    async def _send_to_channel(
        self, broadcaster_id: Optional[int], message: str
    ) -> None:
        """Send a message to a channel."""
        bid = broadcaster_id or self._broadcaster_id
        if bid:
            await self.api.send_message(broadcaster_id=bid, content=message)

    async def _timer_send(self, message: str) -> None:
        """Send function for timed messages."""
        if self._broadcaster_id:
            await self.api.send_message(
                broadcaster_id=self._broadcaster_id,
                content=message,
            )

    # -----------------------------------------------------------------------
    # Built-in loyalty commands
    # -----------------------------------------------------------------------

    def _register_loyalty_commands(self) -> None:
        """Register !rank, !top10, !level commands. Called internally."""

        @self.commands.command("rank", description="Check your XP rank")
        async def rank_cmd(ctx: CommandContext) -> None:
            stats = self.loyalty.get_stats(ctx.sender.user_id)
            if not stats:
                await ctx.reply(f"@{ctx.sender.username}, you don't have any XP yet!")
                return
            rank = self.loyalty.get_rank(ctx.sender.user_id)
            await ctx.reply(
                f"@{ctx.sender.username} — Rank #{rank} | Level {stats.level} | {stats.xp} XP"
            )

        @self.commands.command("top10", description="Show XP leaderboard")
        async def top10_cmd(ctx: CommandContext) -> None:
            top = self.loyalty.leaderboard(limit=10)
            if not top:
                await ctx.reply("No leaderboard data yet!")
                return
            lines = [
                f"#{i+1} {s.username} (Lv{s.level}, {s.xp} XP)"
                for i, s in enumerate(top)
            ]
            await ctx.reply(" | ".join(lines))

        @self.commands.command("level", description="Check your level")
        async def level_cmd(ctx: CommandContext) -> None:
            stats = self.loyalty.get_stats(ctx.sender.user_id)
            if not stats:
                await ctx.reply(f"@{ctx.sender.username}, you're Level 0!")
                return
            await ctx.reply(
                f"@{ctx.sender.username} is Level {stats.level} ({stats.xp} XP)"
            )

    def run(self, host: str = "0.0.0.0", port: int = 8420) -> None:
        """Start the bot (registers loyalty commands, then runs)."""
        if self._loyalty_enabled:
            self._register_loyalty_commands()
        super().run(host=host, port=port)
