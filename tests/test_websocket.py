"""Tests for kickforge_core.websocket Pusher client + event translation."""

import json

import pytest

from kickforge_core.events import (
    ChatMessageEvent,
    EventBus,
    FollowEvent,
    GiftEvent,
    SubscriptionEvent,
)
from kickforge_core.websocket import (
    PUSHER_EVENT_MAP,
    PusherClient,
    _parse_envelope,
    translate_pusher_event,
)


# ---------------------------------------------------------------------------
# Envelope parsing
# ---------------------------------------------------------------------------

class TestParseEnvelope:
    def test_parses_outer_json(self):
        raw = '{"event":"pusher:ping","data":{}}'
        env = _parse_envelope(raw)
        assert env["event"] == "pusher:ping"

    def test_parses_string_data(self):
        """Pusher sends ``data`` as a JSON-encoded string."""
        inner = {"id": "msg1", "content": "hello"}
        raw = json.dumps({
            "event": "App\\Events\\ChatMessageEvent",
            "data": json.dumps(inner),
            "channel": "chatrooms.1.v2",
        })
        env = _parse_envelope(raw)
        assert env["data"] == inner
        assert env["event"] == "App\\Events\\ChatMessageEvent"

    def test_handles_bytes(self):
        raw = b'{"event":"test","data":{}}'
        env = _parse_envelope(raw)
        assert env["event"] == "test"

    def test_non_json_data_left_as_string(self):
        raw = '{"event":"x","data":"not json"}'
        env = _parse_envelope(raw)
        assert env["data"] == "not json"


# ---------------------------------------------------------------------------
# Chat message translation
# ---------------------------------------------------------------------------

CHAT_PAYLOAD = {
    "id": "01HWXYZ",
    "chatroom_id": 123456,
    "content": "!ping",
    "type": "message",
    "created_at": "2026-04-09T12:00:00Z",
    "sender": {
        "id": 42,
        "username": "alice",
        "slug": "alice",
        "identity": {
            "color": "#FF0000",
            "badges": [
                {"type": "subscriber", "text": "Subscriber"},
                {"type": "moderator", "text": "Moderator"},
            ],
        },
    },
}


class TestChatTranslation:
    def test_basic_chat(self):
        result = translate_pusher_event(
            "App\\Events\\ChatMessageEvent",
            CHAT_PAYLOAD,
            broadcaster_user_id=99,
        )
        assert result is not None
        event_type, event = result
        assert event_type == "chat.message.sent"
        assert isinstance(event, ChatMessageEvent)
        assert event.message == "!ping"
        assert event.message_id == "01HWXYZ"
        assert event.broadcaster_user_id == 99
        assert event.sender is not None
        assert event.sender.username == "alice"
        assert event.sender.user_id == 42
        assert event.sender.is_subscriber is True
        assert "moderator" in event.sender.badges

    def test_alternative_event_name(self):
        """Kick may use either ChatMessageEvent or ChatMessageSentEvent."""
        result = translate_pusher_event(
            "App\\Events\\ChatMessageSentEvent",
            CHAT_PAYLOAD,
            broadcaster_user_id=99,
        )
        assert result is not None
        event_type, _ = result
        assert event_type == "chat.message.sent"

    def test_chat_no_badges(self):
        payload = {
            "id": "m1",
            "content": "hi",
            "sender": {"id": 1, "username": "u"},
        }
        result = translate_pusher_event(
            "App\\Events\\ChatMessageEvent", payload, broadcaster_user_id=0
        )
        assert result is not None
        _, event = result
        assert event.sender.is_subscriber is False
        assert event.sender.badges == []

    def test_unknown_event_returns_none(self):
        result = translate_pusher_event("App\\Events\\SomethingNew", {}, 0)
        assert result is None


# ---------------------------------------------------------------------------
# Gift translation
# ---------------------------------------------------------------------------

class TestGiftTranslation:
    def test_kicks_gifted(self):
        payload = {
            "gifter": {"username": "whale", "user_id": 500},
            "amount": 250,
        }
        result = translate_pusher_event(
            "App\\Events\\KicksGiftedEvent",
            payload,
            broadcaster_user_id=99,
        )
        assert result is not None
        event_type, event = result
        assert event_type == "kicks.gifted"
        assert isinstance(event, GiftEvent)
        assert event.gifter_username == "whale"
        assert event.kicks_amount == 250


# ---------------------------------------------------------------------------
# Subscription translation
# ---------------------------------------------------------------------------

class TestSubscriptionTranslation:
    def test_new_sub(self):
        payload = {
            "user": {"id": 77, "username": "newfan"},
            "months": 3,
        }
        result = translate_pusher_event(
            "App\\Events\\SubscriptionEvent", payload, broadcaster_user_id=99
        )
        assert result is not None
        event_type, event = result
        assert event_type == "channel.subscription.new"
        assert isinstance(event, SubscriptionEvent)
        assert event.subscriber_username == "newfan"
        assert event.months == 3
        assert event.is_gift is False

    def test_gifted_subs(self):
        payload = {
            "gifter_username": "bigtipper",
            "gifter_id": 888,
        }
        result = translate_pusher_event(
            "App\\Events\\GiftedSubscriptionsEvent", payload, broadcaster_user_id=99
        )
        assert result is not None
        event_type, event = result
        assert event_type == "channel.subscription.gifts"
        assert event.is_gift is True
        assert event.subscriber_username == "bigtipper"


# ---------------------------------------------------------------------------
# Follow translation
# ---------------------------------------------------------------------------

class TestFollowTranslation:
    def test_follow(self):
        payload = {"username": "newfollower", "user_id": 99}
        result = translate_pusher_event(
            "App\\Events\\FollowersUpdated", payload, broadcaster_user_id=42
        )
        assert result is not None
        event_type, event = result
        assert event_type == "channel.followed"
        assert isinstance(event, FollowEvent)
        assert event.follower_username == "newfollower"


# ---------------------------------------------------------------------------
# PusherClient class
# ---------------------------------------------------------------------------

class TestPusherClient:
    def test_channel_name(self):
        bus = EventBus()
        client = PusherClient(bus=bus, chatroom_id=12345)
        assert client.channel_name == "chatrooms.12345.v2"

    @pytest.mark.asyncio
    async def test_dispatch_emits_on_bus(self):
        bus = EventBus()
        received = []

        @bus.on("chat.message.sent")
        async def handler(event):
            received.append(event.message)

        client = PusherClient(bus=bus, chatroom_id=1, broadcaster_user_id=99)
        envelope = {
            "event": "App\\Events\\ChatMessageEvent",
            "data": CHAT_PAYLOAD,
            "channel": "chatrooms.1.v2",
        }
        await client._dispatch(envelope)
        assert received == ["!ping"]

    @pytest.mark.asyncio
    async def test_dispatch_unknown_event_ignored(self):
        bus = EventBus()
        client = PusherClient(bus=bus, chatroom_id=1)
        envelope = {
            "event": "App\\Events\\SomeUnknownEvent",
            "data": {},
            "channel": "chatrooms.1.v2",
        }
        # Should not raise
        await client._dispatch(envelope)

    @pytest.mark.asyncio
    async def test_dispatch_handles_string_data(self):
        """If _parse_envelope missed the conversion, _dispatch should handle it."""
        bus = EventBus()
        received = []

        @bus.on("chat.message.sent")
        async def handler(event):
            received.append(event.message_id)

        client = PusherClient(bus=bus, chatroom_id=1, broadcaster_user_id=99)
        envelope = {
            "event": "App\\Events\\ChatMessageEvent",
            "data": json.dumps(CHAT_PAYLOAD),  # string, not dict
            "channel": "chatrooms.1.v2",
        }
        await client._dispatch(envelope)
        assert received == ["01HWXYZ"]


# ---------------------------------------------------------------------------
# Event map sanity
# ---------------------------------------------------------------------------

class TestEventMap:
    def test_map_has_core_events(self):
        assert "App\\Events\\ChatMessageEvent" in PUSHER_EVENT_MAP
        assert "App\\Events\\KicksGiftedEvent" in PUSHER_EVENT_MAP
        assert PUSHER_EVENT_MAP["App\\Events\\ChatMessageEvent"] == "chat.message.sent"
