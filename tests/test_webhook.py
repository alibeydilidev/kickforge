"""Tests for kickforge_core.webhook module."""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi.testclient import TestClient

from kickforge_core.events import EventBus
from kickforge_core.webhook import WebhookServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_ed25519_keypair() -> tuple[Ed25519PrivateKey, str]:
    """Generate an Ed25519 keypair, returning (private_key, public_key_pem)."""
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_key, public_pem


def _sign_webhook(
    private_key: Ed25519PrivateKey,
    message_id: str,
    timestamp: str,
    body: bytes,
) -> str:
    """Sign a webhook payload the way Kick does it."""
    message = f"{message_id}{timestamp}".encode() + body
    signature = private_key.sign(message)
    return base64.b64encode(signature).decode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWebhookServer:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def keypair(self):
        return _generate_ed25519_keypair()

    @pytest.fixture
    def server_with_verification(self, bus, keypair):
        _, public_pem = keypair
        server = WebhookServer(bus=bus, verify_signatures=True, public_key=public_pem)
        return server

    @pytest.fixture
    def server_no_verification(self, bus):
        return WebhookServer(bus=bus, verify_signatures=False)

    def test_health_endpoint(self, server_no_verification):
        client = TestClient(server_no_verification.app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "kickforge"}

    def test_webhook_valid_signature(self, server_with_verification, keypair, bus):
        private_key, _ = keypair
        received = []

        @bus.on("chat.message.sent")
        async def handler(event):
            received.append(event)

        body = json.dumps({
            "message_id": "msg-1",
            "content": "hello",
            "sender": {"user_id": 1, "username": "test"},
            "broadcaster_user_id": 99,
        }).encode()

        message_id = "msg-1"
        timestamp = "1700000000"
        signature = _sign_webhook(private_key, message_id, timestamp, body)

        client = TestClient(server_with_verification.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "Kick-Event-Signature": signature,
                "Kick-Event-Message-Id": message_id,
                "Kick-Event-Message-Timestamp": timestamp,
                "Kick-Event-Type": "chat.message.sent",
                "Kick-Event-Subscription-Id": "sub-1",
            },
        )
        assert resp.status_code == 200
        assert len(received) == 1

    def test_webhook_invalid_signature(self, server_with_verification):
        body = json.dumps({"content": "hello"}).encode()

        client = TestClient(server_with_verification.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "Kick-Event-Signature": "badsignature==",
                "Kick-Event-Message-Id": "msg-1",
                "Kick-Event-Message-Timestamp": "1700000000",
                "Kick-Event-Type": "chat.message.sent",
            },
        )
        assert resp.status_code == 403

    def test_webhook_missing_signature(self, server_with_verification):
        body = json.dumps({"content": "hello"}).encode()

        client = TestClient(server_with_verification.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "Kick-Event-Type": "chat.message.sent",
            },
        )
        assert resp.status_code == 403

    def test_webhook_no_verification(self, server_no_verification, bus):
        received = []

        @bus.on("kicks.gifted")
        async def handler(event):
            received.append(event)

        body = json.dumps({
            "gifter": {"username": "user1", "user_id": 1},
            "amount": 100,
            "broadcaster_user_id": 99,
        }).encode()

        client = TestClient(server_no_verification.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "Kick-Event-Type": "kicks.gifted",
            },
        )
        assert resp.status_code == 200
        assert len(received) == 1
        assert received[0].kicks_amount == 100

    def test_webhook_invalid_json(self, server_no_verification):
        client = TestClient(server_no_verification.app)
        resp = client.post(
            "/webhook",
            content=b"not json",
            headers={"Kick-Event-Type": "chat.message.sent"},
        )
        assert resp.status_code == 400

    def test_webhook_tampered_body(self, server_with_verification, keypair):
        """Signature valid for original body, but body is tampered."""
        private_key, _ = keypair

        original_body = json.dumps({"content": "original"}).encode()
        message_id = "msg-1"
        timestamp = "1700000000"
        signature = _sign_webhook(private_key, message_id, timestamp, original_body)

        tampered_body = json.dumps({"content": "hacked"}).encode()

        client = TestClient(server_with_verification.app)
        resp = client.post(
            "/webhook",
            content=tampered_body,
            headers={
                "Kick-Event-Signature": signature,
                "Kick-Event-Message-Id": message_id,
                "Kick-Event-Message-Timestamp": timestamp,
                "Kick-Event-Type": "chat.message.sent",
            },
        )
        assert resp.status_code == 403

    def test_set_public_key(self, bus):
        server = WebhookServer(bus=bus, verify_signatures=True)
        _, pub_pem = _generate_ed25519_keypair()
        server.set_public_key(pub_pem)
        assert server._public_key_pem == pub_pem
        assert server._public_key is None  # Lazy-parsed
