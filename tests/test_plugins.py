"""Tests for kickforge_bot.plugins.base module."""

import pytest

from kickforge_core.events import ChatMessageEvent, FollowEvent, GiftEvent, SubscriptionEvent, Sender
from kickforge_bot.plugins.base import Plugin


class TrackingPlugin(Plugin):
    """Test plugin that records every hook call."""

    name = "tracker"

    def __init__(self):
        self.loaded = False
        self.unloaded = False
        self.messages = []
        self.follows = []
        self.gifts = []
        self.subs = []

    async def on_load(self, bot):
        self.loaded = True

    async def on_unload(self, bot):
        self.unloaded = True

    async def on_message(self, event):
        self.messages.append(event.message)

    async def on_follow(self, event):
        self.follows.append(event.follower_username)

    async def on_gift(self, event):
        self.gifts.append(event.kicks_amount)

    async def on_sub(self, event):
        self.subs.append(event.subscriber_username)


class TestPlugin:
    @pytest.mark.asyncio
    async def test_on_message(self):
        plugin = TrackingPlugin()
        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message="hello",
            sender=Sender(user_id=1, username="u"),
        )
        await plugin.on_message(event)
        assert plugin.messages == ["hello"]

    @pytest.mark.asyncio
    async def test_on_follow(self):
        plugin = TrackingPlugin()
        event = FollowEvent(
            event_type="channel.followed",
            raw={},
            follower_username="newfan",
            follower_user_id=1,
        )
        await plugin.on_follow(event)
        assert plugin.follows == ["newfan"]

    @pytest.mark.asyncio
    async def test_on_gift(self):
        plugin = TrackingPlugin()
        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="generous",
            gifter_user_id=1,
            kicks_amount=100,
        )
        await plugin.on_gift(event)
        assert plugin.gifts == [100]

    @pytest.mark.asyncio
    async def test_on_sub(self):
        plugin = TrackingPlugin()
        event = SubscriptionEvent(
            event_type="channel.subscription.new",
            raw={},
            subscriber_username="newsub",
            subscriber_user_id=1,
        )
        await plugin.on_sub(event)
        assert plugin.subs == ["newsub"]

    @pytest.mark.asyncio
    async def test_default_hooks_are_noop(self):
        """Base Plugin class has no-op defaults — should not raise."""
        plugin = Plugin()
        event = ChatMessageEvent(event_type="chat.message.sent", raw={}, message="x")
        await plugin.on_message(event)
        await plugin.on_load(None)  # type: ignore
        await plugin.on_unload(None)  # type: ignore
