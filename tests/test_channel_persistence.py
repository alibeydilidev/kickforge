"""Tests for channel info persistence + auto-resolve flow."""

import json
import os
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from kickforge_core.auth import KickAuth, TokenPair
from kickforge_core.api import KickAPI
from kickforge_core.oauth_server import OAuthServer


@pytest.fixture
def tmp_token_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    yield Path(path)
    if os.path.exists(path):
        os.unlink(path)


# ---------------------------------------------------------------------------
# save_channel_info / load_channel_info
# ---------------------------------------------------------------------------

class TestChannelInfoPersistence:
    def test_save_and_load_channel_info(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth.save_channel_info(
            chatroom_id=12345,
            broadcaster_user_id=67890,
            slug="mychannel",
        )
        info = auth.load_channel_info()
        assert info["chatroom_id"] == 12345
        assert info["broadcaster_user_id"] == 67890
        assert info["channel_slug"] == "mychannel"

    def test_load_empty_returns_empty_dict(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        assert auth.load_channel_info() == {}

    def test_save_channel_preserves_existing_token(self, tmp_token_file):
        """Saving channel info must not wipe the saved user token."""
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        tp = TokenPair(
            access_token="my-token",
            refresh_token="my-refresh",
            expires_at=time.time() + 3600,
        )
        auth._save_user_token(tp)
        auth.save_channel_info(chatroom_id=99999, slug="foo")

        # Token should still be there
        loaded_tp = auth._load_user_token()
        assert loaded_tp is not None
        assert loaded_tp.access_token == "my-token"
        assert loaded_tp.refresh_token == "my-refresh"

        # And channel info should be there
        info = auth.load_channel_info()
        assert info["chatroom_id"] == 99999

    def test_save_token_preserves_existing_channel_info(self, tmp_token_file):
        """Saving a new token should not wipe previously-saved chatroom_id."""
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth.save_channel_info(chatroom_id=12345, slug="mychannel")

        tp = TokenPair(access_token="fresh-token", expires_at=time.time() + 3600)
        auth._save_user_token(tp)

        info = auth.load_channel_info()
        assert info["chatroom_id"] == 12345
        assert info["channel_slug"] == "mychannel"

    def test_channel_info_chmod_600(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth.save_channel_info(chatroom_id=1)
        mode = tmp_token_file.stat().st_mode & 0o777
        assert mode == 0o600


# ---------------------------------------------------------------------------
# get_chatroom_id try_user_token path
# ---------------------------------------------------------------------------

class TestChatroomIdUserToken:
    @pytest.mark.asyncio
    async def test_try_user_token_success(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth._tokens["user"] = TokenPair(
            access_token="usr-tok", expires_at=time.time() + 3600
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/public/v1/channels" in url:
                # Public API returns no chatroom
                return httpx.Response(200, json={"data": [{"broadcaster_user_id": 10}]})
            if "/api/v2/channels/testchan" in url:
                assert request.headers.get("Authorization") == "Bearer usr-tok"
                return httpx.Response(200, json={
                    "chatroom": {"id": 55555},
                    "user_id": 10,
                })
            return httpx.Response(404)

        # Use a shared transport for both the public API (via KickAPI)
        # and the direct legacy endpoint call.
        transport = httpx.MockTransport(handler)
        auth._http = httpx.AsyncClient(transport=transport)
        api = KickAPI(auth=auth)
        api._http = httpx.AsyncClient(
            base_url="https://api.kick.com", transport=transport
        )

        # Also patch httpx.AsyncClient used inside get_chatroom_id
        import kickforge_core.api as api_module
        original_client = api_module.httpx.AsyncClient

        def make_client(*args, **kwargs):
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        api_module.httpx.AsyncClient = make_client
        try:
            cid = await api.get_chatroom_id("testchan", try_user_token=True)
        finally:
            api_module.httpx.AsyncClient = original_client

        assert cid == 55555
        await api.close()


# ---------------------------------------------------------------------------
# OAuthServer /auth/chatroom POST
# ---------------------------------------------------------------------------

class TestOAuthServerChatroomPost:
    def test_chatroom_post_saves(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth, channel_slug="testchan")
        import asyncio
        server._token_done = asyncio.Event()
        server._chatroom_done = asyncio.Event()

        client = TestClient(server.app)
        resp = client.post(
            "/auth/chatroom",
            json={
                "chatroom_id": 12345,
                "broadcaster_user_id": 67890,
                "slug": "testchan",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["chatroom_id"] == 12345
        assert server.chatroom_id == 12345
        assert server._chatroom_done.is_set()

        # Saved to disk
        info = auth.load_channel_info()
        assert info["chatroom_id"] == 12345
        assert info["channel_slug"] == "testchan"

    def test_chatroom_post_missing_id(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        import asyncio
        server._token_done = asyncio.Event()
        server._chatroom_done = asyncio.Event()

        client = TestClient(server.app)
        resp = client.post("/auth/chatroom", json={"slug": "x"})
        assert resp.status_code == 400
        assert "missing" in resp.json()["error"]

    def test_chatroom_post_invalid_json(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        import asyncio
        server._token_done = asyncio.Event()
        server._chatroom_done = asyncio.Event()

        client = TestClient(server.app)
        resp = client.post(
            "/auth/chatroom",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Success HTML embeds JS when chatroom_id unresolved
# ---------------------------------------------------------------------------

class TestSuccessPageJS:
    def test_embeds_js_when_chatroom_unresolved(self, tmp_token_file):
        from kickforge_core.oauth_server import _success_page

        html = _success_page(chatroom_resolved=False, channel_slug="mychan")
        assert "fetch(" in html
        assert "mychan" in html
        assert "/auth/chatroom" in html
        assert "chatroom.id" in html or "chatroom?.id" in html

    def test_no_js_when_chatroom_resolved(self):
        from kickforge_core.oauth_server import _success_page

        html = _success_page(chatroom_resolved=True, channel_slug="mychan")
        assert "<script>" not in html
        assert "fetch(" not in html

    def test_no_js_when_no_slug(self):
        from kickforge_core.oauth_server import _success_page

        html = _success_page(chatroom_resolved=False, channel_slug=None)
        assert "<script>" not in html
