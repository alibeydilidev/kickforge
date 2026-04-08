"""
KickApp — the one-liner entry point for KickForge.

Ties together auth, webhook server, event bus, and API client
into a single object with a decorator-based developer experience.

Usage:
    from kickforge_core import KickApp

    app = KickApp(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
    )

    @app.on("chat.message.sent")
    async def on_chat(event):
        if event.message.startswith("!hello"):
            await app.say(f"Hey {event.sender.username}!")

    app.run(port=8420)
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Callable, Optional

import uvicorn

from kickforge_core.auth import KickAuth
from kickforge_core.events import EventBus, EventHandler
from kickforge_core.webhook import WebhookServer
from kickforge_core.api import KickAPI
from kickforge_core.exceptions import KickForgeError

logger = logging.getLogger("kickforge.app")


class KickApp:
    """
    The main KickForge application.

    Combines authentication, webhook handling, event dispatch,
    and API access into a single clean interface.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        webhook_path: str = "/webhook",
        verify_signatures: bool = True,
        log_level: str = "INFO",
    ) -> None:
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        self.auth = KickAuth(client_id=client_id, client_secret=client_secret)
        self.bus = EventBus()
        self.webhook = WebhookServer(
            bus=self.bus,
            path=webhook_path,
            verify_signatures=verify_signatures,
        )
        self.api = KickAPI(auth=self.auth)
        self._broadcaster_id: Optional[int] = None
        self._shutdown_event: Optional[asyncio.Event] = None

        logger.info("KickForge initialized (webhook path: %s)", webhook_path)

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
        Connect to a channel — fetches broadcaster ID and subscribes to events.

        Args:
            channel_slug: The channel name (e.g. "yargitay")
        """
        channel_data = await self.api.get_channel(channel_slug)
        channels = channel_data.get("data", [channel_data])
        if isinstance(channels, list) and channels:
            self._broadcaster_id = channels[0].get("broadcaster_user_id")
        elif isinstance(channels, dict):
            self._broadcaster_id = channels.get("broadcaster_user_id")

        if self._broadcaster_id:
            logger.info("Connected to channel '%s' (broadcaster_id=%d)", channel_slug, self._broadcaster_id)
        else:
            logger.warning("Could not resolve broadcaster_id for '%s'", channel_slug)

    async def subscribe(self, events: Optional[list[str]] = None) -> None:
        """
        Subscribe to webhook events.

        Default events: chat messages, follows, subs, gifts, livestream status.
        """
        default_events = [
            "chat.message.sent",
            "channel.followed",
            "channel.subscription.new",
            "channel.subscription.gifts",
            "kicks.gifted",
            "livestream.status.updated",
        ]
        await self.api.subscribe_events(events or default_events)

    # -----------------------------------------------------------------------
    # Run
    # -----------------------------------------------------------------------

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8420,
    ) -> None:
        """
        Start the webhook server.

        This blocks until interrupted (Ctrl+C).
        """
        banner = (
            "\n"
            "+" + "=" * 44 + "+\n"
            "|          KickForge v0.1.0                  |\n"
            "|                                            |\n"
            f"|  Webhook: http://{host}:{port}/webhook       |\n"
            f"|  Health:  http://{host}:{port}/health        |\n"
            "|                                            |\n"
            "|  Waiting for Kick events...                |\n"
            "+" + "=" * 44 + "+\n"
        )
        print(banner)

        config = uvicorn.Config(
            self.webhook.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        loop = asyncio.new_event_loop()
        self._shutdown_event = asyncio.Event()

        async def serve() -> None:
            await server.serve()

        async def shutdown() -> None:
            logger.info("Shutting down KickForge...")
            server.should_exit = True
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
            pass  # Windows doesn't support add_signal_handler

        try:
            loop.run_until_complete(serve())
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()
            logger.info("KickForge stopped.")
