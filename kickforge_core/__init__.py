"""
KickForge Core — The engine that powers every KickForge tool.

Handles Kick OAuth 2.1, webhook ingestion, event dispatch,
and REST API calls so you never touch raw HTTP.

Quick start:
    from kickforge_core import KickApp

    app = KickApp(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
    )

    @app.on("chat.message.sent")
    async def on_chat(event):
        print(f"{event.sender.username}: {event.message}")

    app.run(port=8420)
"""

from kickforge_core.app import KickApp
from kickforge_core.auth import KickAuth, TokenPair, generate_pkce_pair, TOKEN_FILE
from kickforge_core.oauth_server import OAuthServer
from kickforge_core.events import (
    Event,
    EventBus,
    ChatMessageEvent,
    FollowEvent,
    SubscriptionEvent,
    GiftEvent,
    LivestreamStatusEvent,
    Sender,
    parse_event,
)
from kickforge_core.api import KickAPI
from kickforge_core.webhook import WebhookServer
from kickforge_core.websocket import PusherClient, translate_pusher_event
from kickforge_core.exceptions import (
    KickForgeError,
    AuthenticationError,
    TokenExpiredError,
    APIError,
    RateLimitError,
    WebhookVerificationError,
    ConfigurationError,
)

__version__ = "0.2.0"
__all__ = [
    "KickApp",
    "KickAuth",
    "TokenPair",
    "generate_pkce_pair",
    "TOKEN_FILE",
    "OAuthServer",
    "Event",
    "EventBus",
    "ChatMessageEvent",
    "FollowEvent",
    "SubscriptionEvent",
    "GiftEvent",
    "LivestreamStatusEvent",
    "Sender",
    "parse_event",
    "KickAPI",
    "WebhookServer",
    "PusherClient",
    "translate_pusher_event",
    "KickForgeError",
    "AuthenticationError",
    "TokenExpiredError",
    "APIError",
    "RateLimitError",
    "WebhookVerificationError",
    "ConfigurationError",
]
