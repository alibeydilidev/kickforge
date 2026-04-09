"""
Pusher WebSocket client for Kick chat.

Kick's chat system runs on top of Pusher WebSockets, separate from
their webhook system.  Connecting here lets you receive chat messages,
follows, subs, and gifts in real time WITHOUT needing a public HTTPS
endpoint, ngrok, or webhook subscriptions.

The events are translated into the same ``ChatMessageEvent`` /
``FollowEvent`` / ``SubscriptionEvent`` / ``GiftEvent`` models used by
the webhook path, so ``@app.on("chat.message.sent")`` handlers fire
identically whether events come from webhooks or WebSockets.

Protocol reference: https://pusher.com/docs/channels/library_auth_reference/pusher-websockets-protocol/
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from kickforge_core.events import (
    ChatMessageEvent,
    Event,
    EventBus,
    FollowEvent,
    GiftEvent,
    Sender,
    SubscriptionEvent,
)

logger = logging.getLogger("kickforge.websocket")

# Kick's public Pusher app key and cluster.  These are hardcoded in
# Kick's web client and may change — override via the ``ws_url`` param
# to PusherClient if needed.
DEFAULT_WS_URL = (
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
    "?protocol=7&client=js&version=8.4.0-rc2&flash=false"
)


class PusherClient:
    """
    Connects to Kick's Pusher WebSocket and forwards chat events
    to an EventBus.

    Usage:
        client = PusherClient(
            bus=app.bus,
            chatroom_id=12345,
            broadcaster_user_id=67890,
        )
        await client.run()  # blocks until disconnected
    """

    def __init__(
        self,
        bus: EventBus,
        chatroom_id: int,
        broadcaster_user_id: int = 0,
        ws_url: str = DEFAULT_WS_URL,
        reconnect_delay: float = 3.0,
        max_reconnect_attempts: int = -1,  # -1 = forever
    ) -> None:
        self.bus = bus
        self.chatroom_id = chatroom_id
        self.broadcaster_user_id = broadcaster_user_id
        self.ws_url = ws_url
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self._ws: Optional[Any] = None
        self._running = False
        self._socket_id: Optional[str] = None

    @property
    def channel_name(self) -> str:
        """Pusher channel name for this chatroom."""
        return f"chatrooms.{self.chatroom_id}.v2"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Main loop — connects, subscribes, receives, auto-reconnects on drop.
        Blocks until ``stop()`` is called or max reconnects hit.
        """
        self._running = True
        attempt = 0

        while self._running:
            try:
                attempt += 1
                logger.info(
                    "Connecting to Kick Pusher (attempt %d) chatroom=%d",
                    attempt, self.chatroom_id,
                )
                async with websockets.connect(self.ws_url) as ws:  # type: ignore[attr-defined]
                    self._ws = ws
                    await self._handshake(ws)
                    await self._subscribe(ws)
                    attempt = 0  # reset on successful connection
                    await self._receive_loop(ws)
            except ConnectionClosed as exc:
                logger.warning("Pusher connection closed: %s", exc)
            except asyncio.CancelledError:
                logger.info("Pusher client cancelled")
                break
            except Exception:
                logger.exception("Pusher connection error")

            if not self._running:
                break
            if self.max_reconnect_attempts >= 0 and attempt >= self.max_reconnect_attempts:
                logger.error("Max reconnect attempts reached, giving up")
                break

            logger.info("Reconnecting in %.1fs...", self.reconnect_delay)
            await asyncio.sleep(self.reconnect_delay)

    async def stop(self) -> None:
        """Stop the client."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ------------------------------------------------------------------
    # Pusher protocol
    # ------------------------------------------------------------------

    async def _handshake(self, ws: Any) -> None:
        """Wait for pusher:connection_established and capture socket_id."""
        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        envelope = _parse_envelope(raw)
        if envelope.get("event") != "pusher:connection_established":
            raise RuntimeError(
                f"Unexpected first message from Pusher: {envelope.get('event')}"
            )
        data = envelope.get("data", {})
        self._socket_id = data.get("socket_id")
        logger.info("Pusher connected (socket_id=%s)", self._socket_id)

    async def _subscribe(self, ws: Any) -> None:
        """Subscribe to the chatroom channel."""
        subscribe_msg = json.dumps({
            "event": "pusher:subscribe",
            "data": {"channel": self.channel_name},
        })
        await ws.send(subscribe_msg)
        logger.info("Subscribed to %s", self.channel_name)

    async def _receive_loop(self, ws: Any) -> None:
        """Process incoming messages until the connection closes."""
        async for raw in ws:
            try:
                envelope = _parse_envelope(raw)
            except Exception:
                logger.exception("Failed to parse Pusher message: %r", raw[:200])
                continue

            event_name = envelope.get("event", "")

            # Pusher protocol control events
            if event_name == "pusher:ping":
                await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                continue
            if event_name == "pusher:pong":
                continue
            if event_name.startswith("pusher:") or event_name.startswith("pusher_internal:"):
                logger.debug("Pusher control: %s", event_name)
                continue

            # Application event — translate and emit
            try:
                await self._dispatch(envelope)
            except Exception:
                logger.exception("Error dispatching Pusher event %s", event_name)

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    async def _dispatch(self, envelope: dict[str, Any]) -> None:
        """Translate a Pusher envelope to a KickForge Event and emit."""
        pusher_event = envelope.get("event", "")
        data = envelope.get("data", {})
        # Pusher wraps data as a JSON string — _parse_envelope already
        # handles that, but defensive check:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Non-JSON data in Pusher event %s", pusher_event)
                return

        result = translate_pusher_event(
            pusher_event=pusher_event,
            data=data,
            broadcaster_user_id=self.broadcaster_user_id,
        )
        if not result:
            logger.debug("Unhandled Pusher event: %s", pusher_event)
            return

        kickforge_event_type, event_obj = result
        logger.info("Pusher -> EventBus: %s", kickforge_event_type)
        await self.bus.emit(kickforge_event_type, event_obj)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_envelope(raw: str | bytes) -> dict[str, Any]:
    """
    Parse a Pusher message envelope.

    Pusher messages look like:
        {"event": "App\\Events\\ChatMessageEvent",
         "data": "{\"id\":\"...\", ...}",
         "channel": "chatrooms.123.v2"}

    The ``data`` field is a JSON string (not a dict), so we parse it
    once here and return the outer envelope with ``data`` as a dict.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    envelope = json.loads(raw)
    if isinstance(envelope.get("data"), str):
        try:
            envelope["data"] = json.loads(envelope["data"])
        except json.JSONDecodeError:
            pass  # leave as string
    return envelope


# Mapping of Kick's Pusher event names → KickForge event type strings
PUSHER_EVENT_MAP: dict[str, str] = {
    "App\\Events\\ChatMessageEvent": "chat.message.sent",
    "App\\Events\\ChatMessageSentEvent": "chat.message.sent",
    "App\\Events\\FollowersUpdated": "channel.followed",
    "App\\Events\\SubscriptionEvent": "channel.subscription.new",
    "App\\Events\\ChannelSubscriptionEvent": "channel.subscription.new",
    "App\\Events\\GiftedSubscriptionsEvent": "channel.subscription.gifts",
    "App\\Events\\StreamHostEvent": "channel.host",
    "App\\Events\\LivestreamUpdated": "livestream.status.updated",
    "App\\Events\\KicksGiftedEvent": "kicks.gifted",
}


def translate_pusher_event(
    pusher_event: str,
    data: dict[str, Any],
    broadcaster_user_id: int = 0,
) -> Optional[tuple[str, Event]]:
    """
    Translate a Kick Pusher event into a KickForge typed Event.

    Returns (event_type, event_object) or None if the event is unknown.
    """
    kf_event_type = PUSHER_EVENT_MAP.get(pusher_event)
    if not kf_event_type:
        return None

    if kf_event_type == "chat.message.sent":
        return kf_event_type, _build_chat_event(data, broadcaster_user_id)
    if kf_event_type == "channel.followed":
        return kf_event_type, _build_follow_event(data, broadcaster_user_id)
    if kf_event_type == "channel.subscription.new":
        return kf_event_type, _build_sub_event(data, broadcaster_user_id)
    if kf_event_type == "channel.subscription.gifts":
        return kf_event_type, _build_gift_sub_event(data, broadcaster_user_id)
    if kf_event_type == "kicks.gifted":
        return kf_event_type, _build_kicks_event(data, broadcaster_user_id)

    # Generic fallback for events with no specific model (e.g. livestream.status)
    return kf_event_type, Event(
        event_type=kf_event_type,
        raw=data,
        broadcaster_user_id=broadcaster_user_id or None,
    )


def _build_chat_event(data: dict[str, Any], broadcaster_user_id: int) -> ChatMessageEvent:
    """Build ChatMessageEvent from Pusher chat message data."""
    sender_data = data.get("sender", {})
    identity = sender_data.get("identity", {}) or {}
    badges = identity.get("badges", []) or []
    badge_types = [b.get("type", "") for b in badges if isinstance(b, dict)]

    return ChatMessageEvent(
        event_type="chat.message.sent",
        raw=data,
        message_id=str(data.get("id", "")),
        message=str(data.get("content", "")),
        broadcaster_user_id=broadcaster_user_id or None,
        sender=Sender(
            user_id=int(sender_data.get("id", 0)),
            username=str(sender_data.get("username", "")),
            is_subscriber="subscriber" in badge_types,
            badges=badge_types,
        ),
        reply_to=(
            data.get("metadata", {}).get("original_message", {}).get("id")
            if data.get("metadata") else None
        ),
    )


def _build_follow_event(data: dict[str, Any], broadcaster_user_id: int) -> FollowEvent:
    """Build FollowEvent from Pusher follow data."""
    # Kick's FollowersUpdated is a channel-level event with total count;
    # it doesn't include the follower's identity.  We still emit a best-effort
    # FollowEvent so handlers fire.
    return FollowEvent(
        event_type="channel.followed",
        raw=data,
        follower_username=str(data.get("username", "")),
        follower_user_id=int(data.get("user_id", 0)),
        broadcaster_user_id=broadcaster_user_id or None,
    )


def _build_sub_event(data: dict[str, Any], broadcaster_user_id: int) -> SubscriptionEvent:
    """Build SubscriptionEvent from Pusher sub data."""
    user = data.get("user") or data.get("username") or {}
    if isinstance(user, dict):
        username = str(user.get("username", ""))
        user_id = int(user.get("id", 0))
    else:
        username = str(user)
        user_id = int(data.get("user_id", 0))

    return SubscriptionEvent(
        event_type="channel.subscription.new",
        raw=data,
        subscriber_username=username,
        subscriber_user_id=user_id,
        months=int(data.get("months", 1)),
        is_gift=False,
        broadcaster_user_id=broadcaster_user_id or None,
    )


def _build_gift_sub_event(data: dict[str, Any], broadcaster_user_id: int) -> SubscriptionEvent:
    """Build SubscriptionEvent for gifted subs."""
    gifter = data.get("gifter_username", "") or data.get("gifter", {}).get("username", "")
    gifter_id = data.get("gifter_id", 0) or data.get("gifter", {}).get("id", 0)
    return SubscriptionEvent(
        event_type="channel.subscription.gifts",
        raw=data,
        subscriber_username=str(gifter),
        subscriber_user_id=int(gifter_id),
        months=0,
        is_gift=True,
        broadcaster_user_id=broadcaster_user_id or None,
    )


def _build_kicks_event(data: dict[str, Any], broadcaster_user_id: int) -> GiftEvent:
    """Build GiftEvent from Pusher kicks data."""
    gifter = data.get("gifter", {}) or {}
    return GiftEvent(
        event_type="kicks.gifted",
        raw=data,
        gifter_username=str(gifter.get("username", data.get("username", ""))),
        gifter_user_id=int(gifter.get("user_id", gifter.get("id", 0))),
        kicks_amount=int(data.get("amount", data.get("kicks", 0))),
        broadcaster_user_id=broadcaster_user_id or None,
    )
