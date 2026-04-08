"""Tests for kickforge_core.events module."""

import asyncio

import pytest

from kickforge_core.events import (
    ChatMessageEvent,
    Event,
    EventBus,
    FollowEvent,
    GiftEvent,
    LivestreamStatusEvent,
    Sender,
    SubscriptionEvent,
    parse_event,
)


# ---------------------------------------------------------------------------
# Event model tests
# ---------------------------------------------------------------------------

class TestChatMessageEvent:
    def test_from_payload(self, sample_chat_payload):
        event = ChatMessageEvent.from_payload(sample_chat_payload)
        assert event.event_type == "chat.message.sent"
        assert event.message_id == "msg-123"
        assert event.message == "!hello world"
        assert event.broadcaster_user_id == 99999
        assert event.sender is not None
        assert event.sender.username == "testuser"
        assert event.sender.user_id == 12345
        assert event.sender.is_subscriber is True
        assert event.reply_to is None

    def test_from_payload_with_reply(self, sample_chat_payload):
        sample_chat_payload["replied_to"] = {"message_id": "reply-456"}
        event = ChatMessageEvent.from_payload(sample_chat_payload)
        assert event.reply_to == "reply-456"

    def test_from_payload_missing_sender(self):
        event = ChatMessageEvent.from_payload({"content": "hello"})
        assert event.sender is not None
        assert event.sender.username == ""


class TestFollowEvent:
    def test_from_payload(self, sample_follow_payload):
        event = FollowEvent.from_payload(sample_follow_payload)
        assert event.event_type == "channel.followed"
        assert event.follower_username == "newfollower"
        assert event.follower_user_id == 67890


class TestGiftEvent:
    def test_from_payload(self, sample_gift_payload):
        event = GiftEvent.from_payload(sample_gift_payload)
        assert event.event_type == "kicks.gifted"
        assert event.gifter_username == "generousgifter"
        assert event.gifter_user_id == 11111
        assert event.kicks_amount == 50


class TestSubscriptionEvent:
    def test_from_payload(self, sample_sub_payload):
        event = SubscriptionEvent.from_payload(sample_sub_payload)
        assert event.event_type == "channel.subscription.new"
        assert event.subscriber_username == "newsub"
        assert event.months == 1
        assert event.is_gift is False


class TestLivestreamStatusEvent:
    def test_from_payload(self, sample_livestream_payload):
        event = LivestreamStatusEvent.from_payload(sample_livestream_payload)
        assert event.event_type == "livestream.status.updated"
        assert event.is_live is True
        assert event.title == "Playing CS2 with viewers!"


class TestParseEvent:
    def test_known_event_type(self, sample_chat_payload):
        event = parse_event("chat.message.sent", sample_chat_payload)
        assert isinstance(event, ChatMessageEvent)
        assert event.message == "!hello world"

    def test_unknown_event_type(self):
        event = parse_event("some.unknown.event", {"foo": "bar"})
        assert isinstance(event, Event)
        assert event.event_type == "some.unknown.event"
        assert event.raw == {"foo": "bar"}


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------

class TestEventBus:
    @pytest.mark.asyncio
    async def test_on_and_emit(self, sample_chat_payload):
        bus = EventBus()
        received = []

        @bus.on("chat.message.sent")
        async def handler(event):
            received.append(event)

        event = ChatMessageEvent.from_payload(sample_chat_payload)
        await bus.emit("chat.message.sent", event)

        assert len(received) == 1
        assert received[0].message == "!hello world"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, sample_chat_payload):
        bus = EventBus()
        results = []

        @bus.on("chat.message.sent")
        async def handler1(event):
            results.append("h1")

        @bus.on("chat.message.sent")
        async def handler2(event):
            results.append("h2")

        event = ChatMessageEvent.from_payload(sample_chat_payload)
        await bus.emit("chat.message.sent", event)

        assert set(results) == {"h1", "h2"}

    @pytest.mark.asyncio
    async def test_on_all(self, sample_chat_payload):
        bus = EventBus()
        received = []

        @bus.on_all()
        async def global_handler(event):
            received.append(event.event_type)

        event = ChatMessageEvent.from_payload(sample_chat_payload)
        await bus.emit("chat.message.sent", event)
        assert "chat.message.sent" in received

    @pytest.mark.asyncio
    async def test_no_handlers(self, sample_chat_payload):
        bus = EventBus()
        event = ChatMessageEvent.from_payload(sample_chat_payload)
        # Should not raise
        await bus.emit("chat.message.sent", event)

    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self, sample_chat_payload):
        bus = EventBus()
        results = []

        @bus.on("chat.message.sent")
        async def bad_handler(event):
            raise ValueError("boom")

        @bus.on("chat.message.sent")
        async def good_handler(event):
            results.append("ok")

        event = ChatMessageEvent.from_payload(sample_chat_payload)
        await bus.emit("chat.message.sent", event)

        # Good handler should still run despite bad handler raising
        assert "ok" in results

    @pytest.mark.asyncio
    async def test_emit_wrong_type(self):
        bus = EventBus()
        results = []

        @bus.on("chat.message.sent")
        async def handler(event):
            results.append(True)

        event = Event(event_type="other.event", raw={})
        await bus.emit("other.event", event)

        assert len(results) == 0  # Handler only for chat.message.sent
