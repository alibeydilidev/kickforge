"""Tests for PKCE, token persistence, and the OAuth server."""

import base64
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from kickforge_core.auth import (
    KickAuth,
    TokenPair,
    generate_pkce_pair,
    KICK_AUTHORIZE_URL,
)
from kickforge_core.exceptions import TokenExpiredError
from kickforge_core.oauth_server import OAuthServer


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

class TestPKCE:
    def test_generate_pair_returns_strings(self):
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_is_url_safe(self):
        verifier, _ = generate_pkce_pair()
        # Only URL-safe base64 chars (no +/= padding)
        assert all(c.isalnum() or c in "-_" for c in verifier)

    def test_verifier_length(self):
        """Spec: 43-128 chars. 32 random bytes → 43 char URL-safe base64."""
        verifier, _ = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_challenge_matches_s256(self):
        verifier, challenge = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == expected

    def test_pairs_are_random(self):
        v1, c1 = generate_pkce_pair()
        v2, c2 = generate_pkce_pair()
        assert v1 != v2
        assert c1 != c2


# ---------------------------------------------------------------------------
# Authorize URL with PKCE
# ---------------------------------------------------------------------------

class TestAuthorizeUrlPKCE:
    def test_includes_code_challenge(self):
        auth = KickAuth(client_id="cid", client_secret="sec")
        verifier, challenge = generate_pkce_pair()
        url = auth.get_authorize_url(
            redirect_uri="http://localhost:8421/auth/callback",
            scopes=["chat:write"],
            state="abc",
            code_challenge=challenge,
        )
        assert f"code_challenge={challenge}" in url
        assert "code_challenge_method=S256" in url
        assert url.startswith(KICK_AUTHORIZE_URL)

    def test_no_code_challenge_when_not_provided(self):
        auth = KickAuth(client_id="cid", client_secret="sec")
        url = auth.get_authorize_url(
            redirect_uri="http://localhost/cb",
            scopes=["user:read"],
        )
        assert "code_challenge" not in url


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

class TestTokenPersistence:
    @pytest.fixture
    def tmp_token_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # start without the file
        yield Path(path)
        if os.path.exists(path):
            os.unlink(path)

    def test_save_creates_file(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        tp = TokenPair(
            access_token="tok-1",
            refresh_token="ref-1",
            expires_at=time.time() + 3600,
            scope="chat:write",
        )
        auth._save_user_token(tp)
        assert tmp_token_file.exists()

    def test_save_and_load_roundtrip(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        tp = TokenPair(
            access_token="tok-1",
            refresh_token="ref-1",
            expires_at=time.time() + 3600,
            scope="chat:write",
        )
        auth._save_user_token(tp)

        loaded = auth._load_user_token()
        assert loaded is not None
        assert loaded.access_token == "tok-1"
        assert loaded.refresh_token == "ref-1"
        assert loaded.scope == "chat:write"

    def test_load_missing_file_returns_none(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        assert auth._load_user_token() is None

    def test_save_file_has_600_perms(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth._save_user_token(TokenPair(access_token="t"))
        mode = tmp_token_file.stat().st_mode & 0o777
        # Only owner should have read/write
        assert mode == 0o600

    def test_load_corrupted_file_returns_none(self, tmp_token_file):
        tmp_token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_token_file.write_text("not json at all")
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        assert auth._load_user_token() is None

    def test_clear_saved_token(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        auth._save_user_token(TokenPair(access_token="t"))
        assert tmp_token_file.exists()
        auth.clear_saved_token()
        assert not tmp_token_file.exists()


# ---------------------------------------------------------------------------
# get_valid_token auto-loads from disk
# ---------------------------------------------------------------------------

class TestGetValidTokenAutoLoad:
    @pytest.fixture
    def tmp_token_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        yield Path(path)
        if os.path.exists(path):
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_loads_from_disk_on_first_call(self, tmp_token_file):
        # Pre-save a valid token to disk
        tmp_token_file.write_text(
            json.dumps({
                "access_token": "disk-tok",
                "refresh_token": "disk-ref",
                "expires_at": time.time() + 3600,
                "token_type": "Bearer",
                "scope": "chat:write",
            })
        )

        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        token = await auth.get_valid_token("user")
        assert token == "disk-tok"

    @pytest.mark.asyncio
    async def test_raises_when_no_token_and_no_file(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        with pytest.raises(TokenExpiredError, match="kickforge auth"):
            await auth.get_valid_token("user")


# ---------------------------------------------------------------------------
# exchange_code persists to disk
# ---------------------------------------------------------------------------

class TestExchangeCodePersists:
    @pytest.mark.asyncio
    async def test_exchange_saves_to_disk(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        tmp = Path(path)
        try:
            auth = KickAuth(
                client_id="cid", client_secret="sec", token_file=tmp
            )

            async def handler(request: httpx.Request) -> httpx.Response:
                body = request.content.decode()
                assert "authorization_code" in body
                assert "code_verifier=test-verifier" in body
                return httpx.Response(
                    200,
                    json={
                        "access_token": "new-user-tok",
                        "refresh_token": "new-ref",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "chat:write",
                    },
                )

            auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            tp = await auth.exchange_code(
                code="test-code",
                redirect_uri="http://localhost:8421/auth/callback",
                code_verifier="test-verifier",
            )
            assert tp.access_token == "new-user-tok"
            assert tmp.exists()
            saved = json.loads(tmp.read_text())
            assert saved["access_token"] == "new-user-tok"
            await auth.close()
        finally:
            if tmp.exists():
                tmp.unlink()


# ---------------------------------------------------------------------------
# OAuth server routes
# ---------------------------------------------------------------------------

class TestOAuthServerRoutes:
    @pytest.fixture
    def tmp_token_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        yield Path(path)
        if os.path.exists(path):
            os.unlink(path)

    def test_login_redirects_to_kick(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        client = TestClient(server.app, follow_redirects=False)
        resp = client.get("/auth/login")
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert location.startswith(KICK_AUTHORIZE_URL)
        assert "code_challenge" in location
        assert "code_challenge_method=S256" in location
        # State and verifier should be stored on the server
        assert server._state is not None
        assert server._code_verifier is not None

    def test_callback_without_code_returns_error(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        server._done_event = __import__("asyncio").Event()
        client = TestClient(server.app)
        resp = client.get("/auth/callback")
        assert resp.status_code == 400
        assert server.success is False

    def test_callback_with_error_param(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        server._done_event = __import__("asyncio").Event()
        client = TestClient(server.app)
        resp = client.get(
            "/auth/callback?error=access_denied&error_description=User+denied"
        )
        assert resp.status_code == 400
        assert "access_denied" in (server.error or "")

    def test_callback_with_state_mismatch(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        server._state = "expected-state"
        server._code_verifier = "v"
        server._done_event = __import__("asyncio").Event()
        client = TestClient(server.app)
        resp = client.get("/auth/callback?code=abc&state=wrong-state")
        assert resp.status_code == 400
        assert "State mismatch" in (server.error or "")

    def test_redirect_uri_matches_between_authorize_and_exchange(self, tmp_token_file):
        """
        Regression: Kick returns 'invalid redirect uri' if the token
        exchange redirect_uri doesn't match the authorize URL's one.
        Ensure both code paths use the exact same string.
        """
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        captured = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            # Capture what exchange_code sent
            body = request.content.decode()
            import urllib.parse
            parsed = dict(urllib.parse.parse_qsl(body))
            captured["exchange_redirect_uri"] = parsed.get("redirect_uri")
            return httpx.Response(
                200,
                json={
                    "access_token": "t",
                    "refresh_token": "r",
                    "expires_in": 3600,
                    "scope": "chat:write",
                },
            )

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        server = OAuthServer(auth=auth)
        server._state = "s"
        server._code_verifier = "v"
        server._done_event = __import__("asyncio").Event()

        # Grab the authorize URL that /auth/login builds
        client = TestClient(server.app, follow_redirects=False)
        login_resp = client.get("/auth/login")
        import urllib.parse as up
        qs = up.parse_qs(up.urlparse(login_resp.headers["location"]).query)
        authorize_redirect_uri = qs["redirect_uri"][0]

        # Fresh server for callback (state was just regenerated by login)
        server._state = "match-state"
        server._code_verifier = "match-verifier"
        server._done_event = __import__("asyncio").Event()
        resp = client.get("/auth/callback?code=abc&state=match-state")
        assert resp.status_code == 200

        assert authorize_redirect_uri == captured["exchange_redirect_uri"]
        assert authorize_redirect_uri == server.redirect_uri
        # And it's the localhost form, not 127.0.0.1
        assert "localhost" in authorize_redirect_uri
        assert "127.0.0.1" not in authorize_redirect_uri

    def test_callback_success_path(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "user-tok",
                    "refresh_token": "ref-tok",
                    "expires_in": 3600,
                    "scope": "chat:write",
                },
            )

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        server = OAuthServer(auth=auth)
        server._state = "state-123"
        server._code_verifier = "verifier-abc"
        server._done_event = __import__("asyncio").Event()

        client = TestClient(server.app)
        resp = client.get("/auth/callback?code=mycode&state=state-123")
        assert resp.status_code == 200
        assert server.success is True
        assert tmp_token_file.exists()

    def test_root_redirects_to_login(self, tmp_token_file):
        auth = KickAuth(
            client_id="cid", client_secret="sec", token_file=tmp_token_file
        )
        server = OAuthServer(auth=auth)
        client = TestClient(server.app, follow_redirects=False)
        resp = client.get("/")
        assert resp.status_code in (302, 307)
        assert "/auth/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# OAuth server config
# ---------------------------------------------------------------------------

class TestOAuthServerConfig:
    def test_default_port(self):
        auth = KickAuth(client_id="cid", client_secret="sec")
        server = OAuthServer(auth=auth)
        assert server.port == 8421
        assert server.redirect_uri == "http://localhost:8421/auth/callback"

    def test_custom_port(self):
        auth = KickAuth(client_id="cid", client_secret="sec")
        server = OAuthServer(auth=auth, port=9999)
        assert server.port == 9999
        assert "9999" in server.redirect_uri

    def test_default_scopes_include_chat_write(self):
        auth = KickAuth(client_id="cid", client_secret="sec")
        server = OAuthServer(auth=auth)
        assert "chat:write" in server.scopes
