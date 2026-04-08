"""
Typed event models and pub/sub event bus.

Every Kick webhook event is parsed into a typed dataclass,
then dispatched to registered handlers via the EventBus.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("kickforge.events")


# ---------------------------------------------------------------------------
# Event models
# ---------------------------------------------------------------------------

@dataclass
class Sender:
    user_id: int
    username: str
    is_subscriber: bool = False
    badges: list[str] = field(default_factory=list)


@dataclass
class Event:
    """Base event — every webhook payload becomes one of these."""

    event_type: str
    raw: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    broadcaster_user_id: Optional[int] = None


@dataclass
class ChatMessageEvent(Event):
    message_id: str = ""
    message: str = ""
    sender: Optional[Sender] = None
    reply_to: Optional[str] = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChatMessageEvent:
        sender_data = payload.get("sender") or {}
        return cls(
            event_type="chat.message.sent",
            raw=payload,
            message_id=payload.get("message_id", ""),
            message=payload.get("content", ""),
            broadcaster_user_id=payload.get("broadcaster_user_id"),
            sender=Sender(
                user_id=sender_data.get("user_id", 0),
                username=sender_data.get("username", ""),
                is_subscriber=sender_data.get("is_subscriber", False),
                badges=sender_data.get("badges", []),
            ),
            reply_to=payload.get("replied_to", {}).get("message_id") if payload.get("replied_to") else None,
        )


@dataclass
class FollowEvent(Event):
    follower_username: str = ""
    follower_user_id: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FollowEvent:
        return cls(
            event_type="channel.followed",
            raw=payload,
            follower_username=payload.get("username", ""),
            follower_user_id=payload.get("user_id", 0),
            broadcaster_user_id=payload.get("broadcaster_user_id"),
        )


@dataclass
class SubscriptionEvent(Event):
    subscriber_username: str = ""
    subscriber_user_id: int = 0
    months: int = 0
    is_gift: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SubscriptionEvent:
        return cls(
            event_type=payload.get("_event_type", "channel.subscription.new"),
            raw=payload,
            subscriber_username=payload.get("username", ""),
            subscriber_user_id=payload.get("user_id", 0),
            broadcaster_user_id=payload.get("broadcaster_user_id"),
            months=payload.get("months", 0),
            is_gift=payload.get("is_gift", False),
        )


@dataclass
class GiftEvent(Event):
    """Kicks (coins) gifted to the broadcaster."""

    gifter_username: str = ""
    gifter_user_id: int = 0
    kicks_amount: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> GiftEvent:
        return cls(
            event_type="kicks.gifted",
            raw=payload,
            gifter_username=payload.get("gifter", {}).get("username", ""),
            gifter_user_id=payload.get("gifter", {}).get("user_id", 0),
            broadcaster_user_id=payload.get("broadcaster_user_id"),
            kicks_amount=payload.get("amount", 0),
        )


@dataclass
class LivestreamStatusEvent(Event):
    is_live: bool = False
    title: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> LivestreamStatusEvent:
        return cls(
            event_type="livestream.status.updated",
            raw=payload,
            is_live=payload.get("is_live", False),
            title=payload.get("title", ""),
            broadcaster_user_id=payload.get("broadcaster_user_id"),
        )


# Map event type strings to their parser classes
EVENT_PARSERS: dict[str, type] = {
    "chat.message.sent": ChatMessageEvent,
    "channel.followed": FollowEvent,
    "channel.subscription.new": SubscriptionEvent,
    "channel.subscription.renewal": SubscriptionEvent,
    "channel.subscription.gifts": SubscriptionEvent,
    "kicks.gifted": GiftEvent,
    "livestream.status.updated": LivestreamStatusEvent,
}


def parse_event(event_type: str, payload: dict[str, Any]) -> Event:
    """Parse a raw webhook payload into a typed Event."""
    parser_cls = EVENT_PARSERS.get(event_type)
    if parser_cls and hasattr(parser_cls, "from_payload"):
        event = parser_cls.from_payload(payload)
        return event
    # Fallback to generic event
    return Event(event_type=event_type, raw=payload)


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

# Handler type: async function that takes an Event
EventHandler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    """
    Simple pub/sub event bus.

    Usage:
        bus = EventBus()

        @bus.on("chat.message.sent")
        async def handle(event: ChatMessageEvent):
            print(event.message)

        await bus.emit("chat.message.sent", event)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: str) -> Callable:
        """Decorator to register a handler for a specific event type."""
        def decorator(func: EventHandler) -> EventHandler:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(func)
            logger.debug("Registered handler %s for %s", func.__name__, event_type)
            return func
        return decorator

    def on_all(self) -> Callable:
        """Decorator to register a handler for ALL events."""
        def decorator(func: EventHandler) -> EventHandler:
            self._global_handlers.append(func)
            return func
        return decorator

    async def emit(self, event_type: str, event: Event) -> None:
        """Dispatch an event to all matching handlers."""
        handlers = self._handlers.get(event_type, []) + self._global_handlers
        if not handlers:
            logger.debug("No handlers for event %s", event_type)
            return

        tasks = [asyncio.create_task(self._safe_call(h, event)) for h in handlers]
        await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(handler: EventHandler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception("Handler %s raised an exception", handler.__name__)
