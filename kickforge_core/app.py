"""
KickApp — the one-liner entry point for KickForge.

Ties together auth, webhook server, WebSocket chat client, event bus,
and API client into a single object with a decorator-based developer
experience.

Usage:
    from kickforge_core import KickApp

    # Default: WebSocket mode — no ngrok/webhook needed
    app = KickApp()  # reads credentials from .env

    @app.on("chat.message.sent")
    async def on_chat(event):
        if event.message.startswith("!hello"):
            await app.say(f"Hey {event.sender.username}!")

    app.run(channel="yargitay")
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Callable, Optional

import uvicorn
from dotenv import load_dotenv

from kickforge_core.auth import KickAuth
from kickforge_core.events import EventBus, EventHandler
from kickforge_core.webhook import WebhookServer
from kickforge_core.websocket import PusherClient
from kickforge_core.api import KickAPI
from kickforge_core.exceptions import KickForgeError

logger = logging.getLogger("kickforge.app")

# Auto-load .env if present
load_dotenv()


class KickApp:
    """
    The main KickForge application.

    Combines authentication, event dispatch, and API access with a
    choice of event source:

    - ``mode="websocket"`` (default) — connect to Kick's Pusher chat
      WebSocket.  No public URL or ngrok needed.  Chat events only.
    - ``mode="webhook"`` — run a FastAPI webhook server.  Requires a
      public HTTPS URL registered in your Kick Dev App.
    - ``mode="hybrid"`` — run both simultaneously.

    Credentials can be passed directly or read from environment
    variables (KICK_CLIENT_ID, KICK_CLIENT_SECRET).  Place a
    ``.env`` file in your project root and it will be loaded
    automatically.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        mode: str = "websocket",
        webhook_path: str = "/webhook",
        verify_signatures: bool = True,
        log_level: str = "INFO",
    ) -> None:
        if mode not in ("websocket", "webhook", "hybrid"):
            raise KickForgeError(
                f"Invalid mode '{mode}'. Must be 'websocket', 'webhook', or 'hybrid'."
            )

        resolved_id = client_id or os.getenv("KICK_CLIENT_ID", "")
        resolved_secret = client_secret or os.getenv("KICK_CLIENT_SECRET", "")

        if not resolved_id or not resolved_secret:
            raise KickForgeError(
                "Kick credentials required. Pass client_id/client_secret "
                "or set KICK_CLIENT_ID and KICK_CLIENT_SECRET in your .env file."
            )
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        self.mode = mode
        self.auth = KickAuth(client_id=resolved_id, client_secret=resolved_secret)
        self.bus = EventBus()
        self.api = KickAPI(auth=self.auth)

        # Webhook path (only used in webhook/hybrid mode)
        self.webhook: Optional[WebhookServer] = None
        if mode in ("webhook", "hybrid"):
            self.webhook = WebhookServer(
                bus=self.bus,
                path=webhook_path,
                verify_signatures=verify_signatures,
            )

        # WebSocket (only used in websocket/hybrid mode)
        self.pusher: Optional[PusherClient] = None

        self._broadcaster_id: Optional[int] = None
        self._chatroom_id: Optional[int] = None
        self._shutdown_event: Optional[asyncio.Event] = None

        logger.info("KickForge initialized (mode=%s)", mode)

    # -----------------------------------------------------------------------
    # Event registration (decorator API)
    # -----------------------------------------------------------------------

    def on(self, event_type: str) -> Callable:
        """
        Register an event handler.

        @app.on("chat.message.sent")
        async def on_chat(event):
            ...
        """
        return self.bus.on(event_type)

    def on_all(self) -> Callable:
        """Register a handler that fires on every event."""
        return self.bus.on_all()

    # -----------------------------------------------------------------------
    # Convenience methods
    # -----------------------------------------------------------------------

    async def say(self, message: str, reply_to: Optional[str] = None) -> None:
        """Send a chat message to the connected channel."""
        if not self._broadcaster_id:
            logger.error("Cannot send message — no broadcaster_id set. Call app.connect(channel) first.")
            return
        await self.api.send_message(
            broadcaster_id=self._broadcaster_id,
            content=message,
            reply_to=reply_to,
        )

    async def connect(self, channel_slug: str) -> None:
        """
        Connect to a channel — fetches broadcaster ID and chatroom ID.

        Args:
            channel_slug: The channel name (e.g. "yargitay")
        """
        channel_data = await self.api.get_channel(channel_slug)
        channels = channel_data.get("data", [channel_data])
        if isinstance(channels, list) and channels:
            entry = channels[0]
        elif isinstance(channels, dict):
            entry = channels
        else:
            entry = {}

        self._broadcaster_id = entry.get("broadcaster_user_id")

        # Resolve chatroom_id too (needed for websocket mode)
        self._chatroom_id = await self.api.get_chatroom_id(channel_slug)

        if self._broadcaster_id:
            logger.info(
                "Connected to channel '%s' (broadcaster_id=%d, chatroom_id=%s)",
                channel_slug, self._broadcaster_id, self._chatroom_id,
            )
        else:
            logger.warning("Could not resolve broadcaster_id for '%s'", channel_slug)

    async def subscribe(
        self,
        events: Optional[list[str]] = None,
        broadcaster_user_id: Optional[int] = None,
    ) -> None:
        """
        Subscribe to webhook events (only relevant in webhook/hybrid mode).
        """
        bid = broadcaster_user_id or self._broadcaster_id
        if not bid:
            raise KickForgeError(
                "broadcaster_user_id required. Call app.connect(channel) first "
                "or pass broadcaster_user_id explicitly."
            )
        default_events = [
            "chat.message.sent",
            "channel.followed",
            "channel.subscription.new",
            "channel.subscription.gifts",
            "kicks.gifted",
            "livestream.status.updated",
        ]
        await self.api.subscribe_events(events or default_events, broadcaster_user_id=bid)

    # -----------------------------------------------------------------------
    # Run
    # -----------------------------------------------------------------------

    def run(
        self,
        channel: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8420,
    ) -> None:
        """
        Start the event loop in the configured mode.

        Args:
            channel: Channel slug (required for websocket/hybrid mode).
                     If provided in webhook mode, still used for app.say()
                     and event subscription.
            host: Bind address for the webhook server.
            port: Port for the webhook server.

        Blocks until interrupted (Ctrl+C).
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._shutdown_event = asyncio.Event()

        uvicorn_server: Optional[uvicorn.Server] = None
        if self.mode in ("webhook", "hybrid"):
            assert self.webhook is not None
            config = uvicorn.Config(
                self.webhook.app,
                host=host,
                port=port,
                log_level="info",
                access_log=True,
            )
            uvicorn_server = uvicorn.Server(config)

        async def bootstrap() -> None:
            if channel:
                try:
                    await self.connect(channel)
                except Exception:
                    logger.exception("Failed to resolve channel '%s'", channel)

            if self.mode in ("websocket", "hybrid"):
                if not self._chatroom_id:
                    raise KickForgeError(
                        "Could not resolve chatroom_id. "
                        "Pass a valid 'channel' slug to app.run(channel=...)."
                    )
                self.pusher = PusherClient(
                    bus=self.bus,
                    chatroom_id=self._chatroom_id,
                    broadcaster_user_id=self._broadcaster_id or 0,
                )

        async def serve() -> None:
            tasks = []
            if uvicorn_server is not None:
                tasks.append(asyncio.create_task(uvicorn_server.serve()))
            if self.pusher is not None:
                tasks.append(asyncio.create_task(self.pusher.run()))
            if not tasks:
                raise KickForgeError("Nothing to run — check mode configuration")
            await asyncio.gather(*tasks, return_exceptions=True)

        async def shutdown() -> None:
            logger.info("Shutting down KickForge...")
            if uvicorn_server is not None:
                uvicorn_server.should_exit = True
            if self.pusher is not None:
                await self.pusher.stop()
            try:
                await self.api.close()
            except Exception:
                logger.exception("Error during API client shutdown")
            if self._shutdown_event:
                self._shutdown_event.set()

        def signal_handler() -> None:
            loop.create_task(shutdown())

        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
        except NotImplementedError:
            pass  # Windows

        print(_make_banner(self.mode, host, port, channel))

        try:
            loop.run_until_complete(bootstrap())
            loop.run_until_complete(serve())
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown())
        except Exception:
            logger.exception("KickApp crashed")
            loop.run_until_complete(shutdown())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            logger.info("KickForge stopped.")


def _make_banner(mode: str, host: str, port: int, channel: Optional[str]) -> str:
    """Build the startup banner for run()."""
    lines = [
        "",
        "+" + "=" * 52 + "+",
        "|             KickForge v0.1.0                       |",
        "|                                                    |",
        f"|  Mode:     {mode:<40}|",
    ]
    if channel:
        lines.append(f"|  Channel:  {channel:<40}|")
    if mode in ("webhook", "hybrid"):
        lines.append(f"|  Webhook:  http://{host}:{port}/webhook" + " " * max(0, 28 - len(f"{host}:{port}")) + "|")
    if mode in ("websocket", "hybrid"):
        lines.append("|  Source:   Kick Pusher WebSocket (no ngrok needed) |")
    lines.append("|                                                    |")
    lines.append("|  Waiting for Kick events...                        |")
    lines.append("+" + "=" * 52 + "+")
    return "\n".join(lines)
