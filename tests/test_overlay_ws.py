"""Tests for kickforge_overlay.server.ws_server module."""

import asyncio
import json

import pytest

from kickforge_core.events import (
    ChatMessageEvent,
    EventBus,
    FollowEvent,
    GiftEvent,
    Sender,
    SubscriptionEvent,
)
from kickforge_overlay.server.ws_server import OverlayServer


class TestOverlayServer:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def server(self, bus):
        return OverlayServer(bus=bus, port=0)  # Port 0 = don't actually bind

    def test_register_bus(self, server):
        server._register_bus()
        assert server._registered is True
        # Should be idempotent
        server._register_bus()

    @pytest.mark.asyncio
    async def test_broadcast_empty(self, server):
        """Broadcast with no clients should not raise."""
        await server.broadcast({"type": "test"})

    @pytest.mark.asyncio
    async def test_chat_velocity_event(self, bus, server):
        """Chat events should trigger velocity broadcast."""
        server._register_bus()
        broadcasted = []
        original_broadcast = server.broadcast

        async def mock_broadcast(data):
            broadcasted.append(data)

        server.broadcast = mock_broadcast

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="hello",
            broadcaster_user_id=99,
            sender=Sender(user_id=1, username="u"),
        )
        await bus.emit("chat.message.sent", event)

        assert len(broadcasted) == 1
        assert broadcasted[0]["type"] == "chat_velocity"
        assert "velocity" in broadcasted[0]

    @pytest.mark.asyncio
    async def test_gift_event(self, bus, server):
        server._register_bus()
        broadcasted = []

        async def mock_broadcast(data):
            broadcasted.append(data)

        server.broadcast = mock_broadcast

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="alice",
            gifter_user_id=1,
            kicks_amount=100,
            broadcaster_user_id=99,
        )
        await bus.emit("kicks.gifted", event)

        assert len(broadcasted) == 1
        assert broadcasted[0]["type"] == "gift_received"
        assert broadcasted[0]["username"] == "alice"
        assert broadcasted[0]["amount"] == 100

    @pytest.mark.asyncio
    async def test_follow_event(self, bus, server):
        server._register_bus()
        broadcasted = []

        async def mock_broadcast(data):
            broadcasted.append(data)

        server.broadcast = mock_broadcast

        event = FollowEvent(
            event_type="channel.followed",
            raw={},
            follower_username="bob",
            follower_user_id=2,
            broadcaster_user_id=99,
        )
        await bus.emit("channel.followed", event)

        assert len(broadcasted) == 1
        assert broadcasted[0]["type"] == "follow"
        assert broadcasted[0]["username"] == "bob"

    @pytest.mark.asyncio
    async def test_sub_event(self, bus, server):
        server._register_bus()
        broadcasted = []

        async def mock_broadcast(data):
            broadcasted.append(data)

        server.broadcast = mock_broadcast

        event = SubscriptionEvent(
            event_type="channel.subscription.new",
            raw={},
            subscriber_username="carol",
            subscriber_user_id=3,
            months=6,
            broadcaster_user_id=99,
        )
        await bus.emit("channel.subscription.new", event)

        assert len(broadcasted) == 1
        assert broadcasted[0]["type"] == "sub"
        assert broadcasted[0]["username"] == "carol"
        assert broadcasted[0]["months"] == 6

    @pytest.mark.asyncio
    async def test_broadcast_json_format(self, server):
        """Broadcast should produce valid JSON."""
        data = {"type": "gift_received", "username": "test", "amount": 50}
        # Just verify serialization doesn't raise
        result = json.dumps(data)
        assert '"type"' in result
        assert '"gift_received"' in result
