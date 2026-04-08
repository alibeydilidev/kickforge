"""
WebSocket server for real-time OBS overlay widgets.

Broadcasts JSON events to all connected widget clients.
Attaches to the KickApp EventBus and forwards relevant events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol

from kickforge_core.events import (
    ChatMessageEvent,
    EventBus,
    FollowEvent,
    GiftEvent,
    SubscriptionEvent,
)

logger = logging.getLogger("kickforge.overlay.ws")


class OverlayServer:
    """
    WebSocket server that broadcasts events to OBS overlay widgets.

    Usage:
        server = OverlayServer(bus=app.bus, port=8765)
        await server.start()
        # widgets connect to ws://localhost:8765
        await server.stop()
    """

    def __init__(
        self,
        bus: EventBus,
        port: int = 8765,
        host: str = "0.0.0.0",
    ) -> None:
        self.bus = bus
        self.port = port
        self.host = host
        self._clients: Set[WebSocketServerProtocol] = set()
        self._server: Optional[Any] = None
        self._registered = False
        self._chat_times: deque[float] = deque()
        self._velocity_window = 60.0

    async def start(self) -> None:
        """Start the WebSocket server and register event handlers."""
        self._register_bus()
        self._server = await websockets.serve(  # type: ignore[attr-defined]
            self._handler, self.host, self.port
        )
        logger.info("Overlay WebSocket server started on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()
        logger.info("Overlay WebSocket server stopped")

    async def _handler(self, ws: WebSocketServerProtocol, path: str = "/") -> None:
        self._clients.add(ws)
        logger.debug("Widget connected (%d total)", len(self._clients))
        try:
            async for _ in ws:
                pass  # Widgets only receive, no inbound messages needed
        finally:
            self._clients.discard(ws)
            logger.debug("Widget disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON payload to all connected widgets."""
        if not self._clients:
            return
        message = json.dumps(data)
        disconnected = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except Exception:
                disconnected.add(ws)
        self._clients -= disconnected

    def _register_bus(self) -> None:
        if self._registered:
            return

        @self.bus.on("chat.message.sent")
        async def _on_chat(event: ChatMessageEvent) -> None:
            now = time.time()
            self._chat_times.append(now)
            # Prune old
            cutoff = now - self._velocity_window
            while self._chat_times and self._chat_times[0] < cutoff:
                self._chat_times.popleft()
            velocity = len(self._chat_times) / self._velocity_window * 60  # msgs/min
            await self.broadcast({
                "type": "chat_velocity",
                "velocity": round(velocity, 1),
                "message_count": len(self._chat_times),
            })

        @self.bus.on("kicks.gifted")
        async def _on_gift(event: GiftEvent) -> None:
            await self.broadcast({
                "type": "gift_received",
                "username": event.gifter_username,
                "amount": event.kicks_amount,
            })

        @self.bus.on("channel.followed")
        async def _on_follow(event: FollowEvent) -> None:
            await self.broadcast({
                "type": "follow",
                "username": event.follower_username,
            })

        @self.bus.on("channel.subscription.new")
        async def _on_sub(event: SubscriptionEvent) -> None:
            await self.broadcast({
                "type": "sub",
                "username": event.subscriber_username,
                "months": event.months,
            })

        @self.bus.on("heat_moment")
        async def _on_heat(event: Any) -> None:
            await self.broadcast({
                "type": "heat_score",
                "score": event.raw.get("score", 0),
                "mps": event.raw.get("mps", 0),
            })

        self._registered = True
