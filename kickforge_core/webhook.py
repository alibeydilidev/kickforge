"""
Kick webhook receiver.

Listens for incoming HTTP POST requests from Kick,
verifies the Ed25519 signature, parses the payload,
and dispatches typed events through the EventBus.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature
from fastapi import FastAPI, Request, Response, HTTPException
import httpx

from kickforge_core.events import EventBus, parse_event
from kickforge_core.exceptions import WebhookVerificationError

logger = logging.getLogger("kickforge.webhook")

KICK_PUBLIC_KEY_URL = "https://api.kick.com/public-key"


class WebhookServer:
    """
    FastAPI-based webhook server for Kick events.

    Usage:
        bus = EventBus()
        server = WebhookServer(bus=bus)
        # Mount server.app with uvicorn
    """

    def __init__(
        self,
        bus: EventBus,
        path: str = "/webhook",
        verify_signatures: bool = True,
        public_key: Optional[str] = None,
    ) -> None:
        self.bus = bus
        self.path = path
        self.verify_signatures = verify_signatures
        self._public_key_pem: Optional[str] = public_key
        self._public_key: Optional[Ed25519PublicKey] = None
        self.app = FastAPI(
            title="KickForge Webhook",
            version="0.1.0",
            docs_url=None,
            redoc_url=None,
        )
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.post(self.path)
        async def handle_webhook(request: Request) -> Response:
            body = await request.body()

            if self.verify_signatures:
                signature = request.headers.get("Kick-Event-Signature", "")
                message_id = request.headers.get("Kick-Event-Message-Id", "")
                timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")

                if not await self._verify_signature(body, signature, message_id, timestamp):
                    logger.warning("Invalid webhook signature — rejecting request")
                    raise HTTPException(status_code=403, detail="Invalid signature")

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON")

            event_type = request.headers.get(
                "Kick-Event-Type",
                payload.get("event_type", "unknown"),
            )
            subscription_id = request.headers.get("Kick-Event-Subscription-Id", "")

            logger.info(
                "Received webhook: type=%s subscription=%s",
                event_type,
                subscription_id,
            )

            event = parse_event(event_type, payload)
            await self.bus.emit(event_type, event)

            return Response(status_code=200)

        @self.app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "service": "kickforge"}

    async def _verify_signature(
        self,
        body: bytes,
        signature: str,
        message_id: str,
        timestamp: str,
    ) -> bool:
        """
        Verify the webhook signature using Kick's Ed25519 public key.

        Kick signs: message_id + timestamp + body
        Signature header is base64-encoded Ed25519 signature.
        """
        if not signature:
            return False

        try:
            public_key = await self._get_public_key()
            if not public_key:
                logger.warning("No public key available — skipping verification")
                return True

            message = f"{message_id}{timestamp}".encode() + body
            signature_bytes = base64.b64decode(signature)

            public_key.verify(signature_bytes, message)
            return True

        except InvalidSignature:
            logger.warning("Ed25519 signature verification failed")
            return False
        except Exception:
            logger.exception("Signature verification error")
            return False

    async def _get_public_key(self) -> Optional[Ed25519PublicKey]:
        """Fetch and cache Kick's webhook Ed25519 public key."""
        if self._public_key is not None:
            return self._public_key

        pem = self._public_key_pem
        if not pem:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(KICK_PUBLIC_KEY_URL)
                    response.raise_for_status()
                    data = response.json()
                    pem = data.get("public_key", "")
                    if not pem:
                        logger.error("Empty public key from Kick API")
                        return None
                    logger.info("Fetched Kick Ed25519 public key")
            except httpx.HTTPError:
                logger.exception("Failed to fetch Kick public key")
                return None

        try:
            key = load_pem_public_key(pem.encode())
            if not isinstance(key, Ed25519PublicKey):
                raise WebhookVerificationError("Kick public key is not Ed25519")
            self._public_key = key
            self._public_key_pem = pem
            return self._public_key
        except Exception:
            logger.exception("Failed to parse Ed25519 public key")
            return None

    def set_public_key(self, pem: str) -> None:
        """Set the Ed25519 public key directly (useful for testing)."""
        self._public_key_pem = pem
        self._public_key = None  # Will be parsed on next verification
