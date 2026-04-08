"""Tests for kickforge_core.app module."""

import time

import httpx
import pytest

from kickforge_core.app import KickApp
from kickforge_core.auth import TokenPair
from kickforge_core.events import ChatMessageEvent


class TestKickApp:
    @pytest.fixture
    def app(self):
        a = KickApp(
            client_id="test-id",
            client_secret="test-secret",
            verify_signatures=False,
            log_level="WARNING",
        )
        return a

    def test_init(self, app):
        assert app.auth.client_id == "test-id"
        assert app.bus is not None
        assert app.webhook is not None
        assert app.api is not None

    def test_on_decorator(self, app):
        @app.on("chat.message.sent")
        async def handler(event):
            pass

        assert "chat.message.sent" in app.bus._handlers
        assert len(app.bus._handlers["chat.message.sent"]) == 1

    def test_on_all_decorator(self, app):
        @app.on_all()
        async def handler(event):
            pass

        assert len(app.bus._global_handlers) == 1

    @pytest.mark.asyncio
    async def test_say_no_broadcaster(self, app):
        # Should not raise, just log error
        await app.say("hello")

    @pytest.mark.asyncio
    async def test_connect(self, app):
        app.auth._tokens["app"] = TokenPair(
            access_token="tok", expires_at=time.time() + 3600
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "data": [{"broadcaster_user_id": 42, "slug": "testchannel"}]
            })

        app.api._http = httpx.AsyncClient(
            base_url="https://api.kick.com",
            transport=httpx.MockTransport(handler),
        )
        await app.connect("testchannel")
        assert app._broadcaster_id == 42
        await app.api.close()

    @pytest.mark.asyncio
    async def test_event_handler_receives_events(self, app):
        received = []

        @app.on("chat.message.sent")
        async def handler(event):
            received.append(event.message)

        event = ChatMessageEvent.from_payload({
            "message_id": "1",
            "content": "test message",
            "sender": {"user_id": 1, "username": "u"},
        })
        await app.bus.emit("chat.message.sent", event)
        assert received == ["test message"]

    @pytest.mark.asyncio
    async def test_subscribe(self, app):
        app.auth._tokens["app"] = TokenPair(
            access_token="tok", expires_at=time.time() + 3600
        )
        subscribed_events = []

        async def handler(request: httpx.Request) -> httpx.Response:
            import json
            data = json.loads(request.content)
            subscribed_events.extend([e["name"] for e in data["events"]])
            return httpx.Response(200, json={"data": {}})

        app.api._http = httpx.AsyncClient(
            base_url="https://api.kick.com",
            transport=httpx.MockTransport(handler),
        )
        app._broadcaster_id = 99
        await app.subscribe()
        assert "chat.message.sent" in subscribed_events
        assert "kicks.gifted" in subscribed_events
        await app.api.close()
