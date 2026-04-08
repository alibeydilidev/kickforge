"""
Command handler — decorator-based command registration, parsing, cooldowns, permissions.

Usage:
    handler = CommandHandler(prefix="!")

    @handler.command("!ping", cooldown=5)
    async def ping(ctx: CommandContext):
        await ctx.reply("pong!")

    # Process incoming chat event
    await handler.process(event, send_func)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from kickforge_core.events import ChatMessageEvent, Sender

logger = logging.getLogger("kickforge.bot.commands")

PERMISSION_LEVELS = {
    "everyone": 0,
    "subscriber": 1,
    "moderator": 2,
    "broadcaster": 3,
}


@dataclass
class CommandContext:
    """Context passed to every command handler."""

    event: ChatMessageEvent
    command: str
    args: list[str]
    sender: Sender
    broadcaster_id: int
    _send: Callable[..., Coroutine[Any, Any, None]] = field(repr=False)
    _reply: Callable[..., Coroutine[Any, Any, None]] = field(repr=False)

    async def reply(self, message: str) -> None:
        """Reply to the message (sends as reply)."""
        await self._reply(message)

    async def send(self, message: str) -> None:
        """Send a message (non-reply)."""
        await self._send(message)


@dataclass
class CommandDefinition:
    """Internal representation of a registered command."""

    name: str
    handler: Callable[[CommandContext], Coroutine[Any, Any, None]]
    cooldown: float = 0.0
    permission: str = "everyone"
    description: str = ""
    _last_used: dict[str, float] = field(default_factory=dict)

    def is_on_cooldown(self, user_key: str = "__global__") -> float:
        """Return remaining cooldown seconds, or 0 if ready."""
        if self.cooldown <= 0:
            return 0.0
        last = self._last_used.get(user_key, 0.0)
        remaining = self.cooldown - (time.time() - last)
        return max(0.0, remaining)

    def mark_used(self, user_key: str = "__global__") -> None:
        """Mark the command as used (reset cooldown)."""
        self._last_used[user_key] = time.time()


class CommandHandler:
    """
    Registers and dispatches bot commands from chat messages.

    Supports:
    - Cooldowns (per-command global)
    - Permission levels (everyone, subscriber, moderator, broadcaster)
    - Argument parsing (space-separated)
    """

    def __init__(self, prefix: str = "!") -> None:
        self.prefix = prefix
        self._commands: dict[str, CommandDefinition] = {}

    def command(
        self,
        name: str,
        cooldown: float = 0.0,
        permission: str = "everyone",
        description: str = "",
    ) -> Callable:
        """Decorator to register a command."""
        cmd_name = name.lstrip(self.prefix).lower()

        def decorator(
            func: Callable[[CommandContext], Coroutine[Any, Any, None]],
        ) -> Callable[[CommandContext], Coroutine[Any, Any, None]]:
            cmd_def = CommandDefinition(
                name=cmd_name,
                handler=func,
                cooldown=cooldown,
                permission=permission,
                description=description or func.__doc__ or "",
            )
            self._commands[cmd_name] = cmd_def
            logger.debug("Registered command: %s%s", self.prefix, cmd_name)
            return func

        return decorator

    def get_commands(self) -> dict[str, CommandDefinition]:
        """Return all registered commands."""
        return dict(self._commands)

    async def process(
        self,
        event: ChatMessageEvent,
        send_func: Callable[[int, str, Optional[str]], Coroutine[Any, Any, None]],
    ) -> bool:
        """
        Process a chat event. Returns True if a command was found and executed.

        Args:
            event: The incoming chat message event.
            send_func: async callable(broadcaster_id, content, reply_to) for sending messages.
        """
        if not event.message or not event.message.startswith(self.prefix):
            return False

        parts = event.message.strip().split()
        cmd_name = parts[0].lstrip(self.prefix).lower()
        args = parts[1:]

        cmd_def = self._commands.get(cmd_name)
        if not cmd_def:
            return False

        sender = event.sender or Sender(user_id=0, username="unknown")
        broadcaster_id = event.broadcaster_user_id or 0

        # Permission check
        user_level = _get_user_permission_level(sender)
        required_level = PERMISSION_LEVELS.get(cmd_def.permission, 0)
        if user_level < required_level:
            logger.debug(
                "User %s lacks permission for %s (has %d, needs %d)",
                sender.username, cmd_name, user_level, required_level,
            )
            return False

        # Cooldown check
        remaining = cmd_def.is_on_cooldown()
        if remaining > 0:
            logger.debug("Command %s on cooldown (%.1fs remaining)", cmd_name, remaining)
            return False

        # Build context
        async def reply(msg: str) -> None:
            await send_func(broadcaster_id, msg, event.message_id)

        async def send(msg: str) -> None:
            await send_func(broadcaster_id, msg, None)

        ctx = CommandContext(
            event=event,
            command=cmd_name,
            args=args,
            sender=sender,
            broadcaster_id=broadcaster_id,
            _send=send,
            _reply=reply,
        )

        try:
            await cmd_def.handler(ctx)
            cmd_def.mark_used()
            logger.info("Executed command: %s%s by %s", self.prefix, cmd_name, sender.username)
        except Exception:
            logger.exception("Command %s raised an exception", cmd_name)

        return True


def _get_user_permission_level(sender: Sender) -> int:
    """Determine a user's permission level from badges."""
    badges = [b.lower() for b in sender.badges]
    if "broadcaster" in badges:
        return PERMISSION_LEVELS["broadcaster"]
    if "moderator" in badges:
        return PERMISSION_LEVELS["moderator"]
    if sender.is_subscriber or "subscriber" in badges:
        return PERMISSION_LEVELS["subscriber"]
    return PERMISSION_LEVELS["everyone"]
