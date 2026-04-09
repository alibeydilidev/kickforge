"""Tests for kickforge_core.auth module."""

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from kickforge_core.auth import KickAuth, TokenPair, KICK_TOKEN_URL, KICK_AUTHORIZE_URL
from kickforge_core.exceptions import AuthenticationError, TokenExpiredError


# ---------------------------------------------------------------------------
# TokenPair
# ---------------------------------------------------------------------------

class TestTokenPair:
    def test_not_expired(self):
        tp = TokenPair(access_token="tok", expires_at=time.time() + 300)
        assert not tp.is_expired

    def test_expired(self):
        tp = TokenPair(access_token="tok", expires_at=time.time() - 10)
        assert tp.is_expired

    def test_expired_within_safety_margin(self):
        tp = TokenPair(access_token="tok", expires_at=time.time() + 30)
        assert tp.is_expired  # 30s < 60s safety margin


# ---------------------------------------------------------------------------
# Mock transport for httpx
# ---------------------------------------------------------------------------

def _make_token_response(
    access_token: str = "test-access-token",
    refresh_token: str | None = None,
    expires_in: int = 3600,
    status_code: int = 200,
):
    body = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": "chat:write",
    }
    if refresh_token:
        body["refresh_token"] = refresh_token
    return httpx.Response(status_code, json=body)


def _make_error_response(status_code: int = 401, error: str = "invalid_client"):
    return httpx.Response(status_code, json={"error": error, "error_description": "Bad creds"})


# ---------------------------------------------------------------------------
# KickAuth tests
# ---------------------------------------------------------------------------

class TestKickAuth:
    @pytest.fixture
    def auth(self, tmp_path):
        # Use a temp token_file so tests don't touch ~/.kickforge/tokens.json
        return KickAuth(
            client_id="test-id",
            client_secret="test-secret",
            token_file=tmp_path / "tokens.json",
        )

    @pytest.mark.asyncio
    async def test_get_app_token(self, auth):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "client_credentials" in str(request.content)
            return _make_token_response()

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        token = await auth.get_app_token()
        assert token == "test-access-token"
        await auth.close()

    @pytest.mark.asyncio
    async def test_get_app_token_cached(self, auth):
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _make_token_response()

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await auth.get_app_token()
        await auth.get_app_token()
        assert call_count == 1  # Second call should use cache
        await auth.close()

    @pytest.mark.asyncio
    async def test_get_app_token_error(self, auth):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _make_error_response()

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(AuthenticationError, match="401"):
            await auth.get_app_token()
        await auth.close()

    def test_get_authorize_url(self, auth):
        url = auth.get_authorize_url(
            redirect_uri="http://localhost:8080/callback",
            scopes=["chat:write", "user:read"],
            state="test-state",
        )
        assert url.startswith(KICK_AUTHORIZE_URL)
        assert "client_id=test-id" in url
        assert "response_type=code" in url
        assert "state=test-state" in url
        assert "scope=chat%3Awrite+user%3Aread" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in url

    @pytest.mark.asyncio
    async def test_exchange_code(self, auth):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "authorization_code" in str(request.content)
            return _make_token_response(
                access_token="user-token",
                refresh_token="user-refresh",
            )

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        tp = await auth.exchange_code(code="test-code", redirect_uri="http://localhost/cb")
        assert tp.access_token == "user-token"
        assert tp.refresh_token == "user-refresh"
        await auth.close()

    @pytest.mark.asyncio
    async def test_refresh_user_token(self, auth):
        # Set up an expired user token
        auth._tokens["user"] = TokenPair(
            access_token="old-token",
            refresh_token="refresh-tok",
            expires_at=time.time() - 100,
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "refresh_token" in str(request.content)
            return _make_token_response(access_token="new-user-token")

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        token = await auth.refresh_user_token()
        assert token == "new-user-token"
        await auth.close()

    @pytest.mark.asyncio
    async def test_refresh_no_user_token(self, auth):
        with pytest.raises(TokenExpiredError):
            await auth.refresh_user_token()

    @pytest.mark.asyncio
    async def test_get_valid_token_app(self, auth):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _make_token_response()

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        token = await auth.get_valid_token("app")
        assert token == "test-access-token"
        await auth.close()

    @pytest.mark.asyncio
    async def test_get_valid_token_user_not_set(self, auth):
        with pytest.raises(TokenExpiredError):
            await auth.get_valid_token("user")

    @pytest.mark.asyncio
    async def test_revoke_token(self, auth):
        revoke_called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal revoke_called
            revoke_called = True
            return httpx.Response(200)

        auth._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await auth.revoke_token("some-token")
        assert revoke_called
        await auth.close()
