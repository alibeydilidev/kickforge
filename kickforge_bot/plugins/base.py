"""
Plugin interface for KickBot.

Plugins receive lifecycle hooks and can react to events.

Usage:
    class MyPlugin(Plugin):
        async def on_load(self, bot):
            print("Plugin loaded!")

        async def on_message(self, event):
            print(f"Message: {event.message}")

    bot.load_plugin(MyPlugin())
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from kickforge_core.events import (
    ChatMessageEvent,
    FollowEvent,
    GiftEvent,
    SubscriptionEvent,
)

if TYPE_CHECKING:
    from kickforge_bot.bot import KickBot


class Plugin(ABC):
    """
    Abstract base class for KickBot plugins.

    Override any hook method you need. All hooks are optional —
    the default implementation is a no-op.
    """

    name: str = "unnamed_plugin"

    async def on_load(self, bot: KickBot) -> None:
        """Called when the plugin is loaded into the bot."""

    async def on_unload(self, bot: KickBot) -> None:
        """Called when the plugin is removed from the bot."""

    async def on_message(self, event: ChatMessageEvent) -> None:
        """Called on every chat message."""

    async def on_follow(self, event: FollowEvent) -> None:
        """Called when someone follows the channel."""

    async def on_gift(self, event: GiftEvent) -> None:
        """Called when kicks are gifted."""

    async def on_sub(self, event: SubscriptionEvent) -> None:
        """Called on new or renewed subscriptions."""
