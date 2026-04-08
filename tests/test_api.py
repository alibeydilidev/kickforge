"""Tests for kickforge_core.api module."""

import json

import httpx
import pytest

from kickforge_core.auth import KickAuth
from kickforge_core.api import KickAPI
from kickforge_core.exceptions import APIError, RateLimitError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_with_token() -> KickAuth:
    """Create a KickAuth that returns a pre-set token without HTTP calls."""
    auth = KickAuth(client_id="test", client_secret="secret")
    from kickforge_core.auth import TokenPair
    import time
    auth._tokens["app"] = TokenPair(
        access_token="mock-token",
        expires_at=time.time() + 3600,
    )
    return auth


def _mock_api(responses: dict[str, httpx.Response]) -> KickAPI:
    """
    Create a KickAPI with a mock transport.
    `responses` maps URL path substrings to httpx.Response objects.
    """
    auth = _make_auth_with_token()
    api = KickAPI(auth=auth)

    async def handler(request: httpx.Request) -> httpx.Response:
        for path, response in responses.items():
            if path in str(request.url):
                return response
        return httpx.Response(404, json={"message": "Not found"})

    api._http = httpx.AsyncClient(
        base_url="https://api.kick.com",
        transport=httpx.MockTransport(handler),
    )
    return api


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKickAPI:
    @pytest.mark.asyncio
    async def test_send_message(self):
        api = _mock_api({
            "/public/v1/chat": httpx.Response(200, json={"data": {"message_id": "new-msg"}}),
        })
        result = await api.send_message(broadcaster_id=99, content="Hello!")
        assert result["data"]["message_id"] == "new-msg"
        await api.close()

    @pytest.mark.asyncio
    async def test_send_message_truncates(self):
        """Message content should be truncated to 500 chars."""
        captured_payload = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"data": {}})

        auth = _make_auth_with_token()
        api = KickAPI(auth=auth)
        api._http = httpx.AsyncClient(
            base_url="https://api.kick.com",
            transport=httpx.MockTransport(handler),
        )

        await api.send_message(broadcaster_id=99, content="x" * 600)
        assert len(captured_payload["content"]) == 500
        await api.close()

    @pytest.mark.asyncio
    async def test_get_channel(self):
        api = _mock_api({
            "/public/v1/channels": httpx.Response(200, json={
                "data": [{"broadcaster_user_id": 99, "slug": "test"}]
            }),
        })
        result = await api.get_channel("test")
        assert result["data"][0]["slug"] == "test"
        await api.close()

    @pytest.mark.asyncio
    async def test_get_livestream(self):
        api = _mock_api({
            "/public/v1/livestreams": httpx.Response(200, json={
                "data": {"is_live": True, "title": "Live!"}
            }),
        })
        result = await api.get_livestream(99)
        assert result["data"]["is_live"] is True
        await api.close()

    @pytest.mark.asyncio
    async def test_ban_user(self):
        api = _mock_api({
            "/public/v1/moderation/bans": httpx.Response(200, json={"data": {"success": True}}),
        })
        # Need a user token for ban
        import time
        from kickforge_core.auth import TokenPair
        api.auth._tokens["user"] = TokenPair(
            access_token="user-tok", expires_at=time.time() + 3600
        )
        result = await api.ban_user(broadcaster_id=99, user_id=123, duration=600)
        assert result["data"]["success"] is True
        await api.close()

    @pytest.mark.asyncio
    async def test_subscribe_events(self):
        api = _mock_api({
            "/public/v1/events/subscriptions": httpx.Response(200, json={"data": {"count": 2}}),
        })
        result = await api.subscribe_events(["chat.message.sent", "kicks.gifted"], broadcaster_user_id=99)
        assert result["data"]["count"] == 2
        await api.close()

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        api = _mock_api({
            "/public/v1/events/subscriptions": httpx.Response(200, json={"data": []}),
        })
        result = await api.get_subscriptions()
        assert result["data"] == []
        await api.close()

    @pytest.mark.asyncio
    async def test_get_kicks_leaderboard(self):
        api = _mock_api({
            "/public/v1/kicks/leaderboard": httpx.Response(200, json={
                "data": [{"username": "top1", "amount": 1000}]
            }),
        })
        result = await api.get_kicks_leaderboard(99)
        assert result["data"][0]["username"] == "top1"
        await api.close()

    @pytest.mark.asyncio
    async def test_api_error_4xx(self):
        api = _mock_api({
            "/public/v1/chat": httpx.Response(400, json={"message": "Bad request"}),
        })
        with pytest.raises(APIError) as exc_info:
            await api.send_message(broadcaster_id=99, content="fail")
        assert exc_info.value.status_code == 400
        await api.close()

    @pytest.mark.asyncio
    async def test_api_rate_limit(self):
        auth = _make_auth_with_token()
        api = KickAPI(auth=auth)

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "30"}, json={})

        api._http = httpx.AsyncClient(
            base_url="https://api.kick.com",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RateLimitError) as exc_info:
            await api.send_message(broadcaster_id=99, content="spam")
        assert exc_info.value.retry_after == 30.0
        await api.close()

    @pytest.mark.asyncio
    async def test_delete_message(self):
        api = _mock_api({
            "/public/v1/chat/msg-1": httpx.Response(200, json={"data": {"deleted": True}}),
        })
        import time
        from kickforge_core.auth import TokenPair
        api.auth._tokens["user"] = TokenPair(
            access_token="user-tok", expires_at=time.time() + 3600
        )
        result = await api.delete_message("msg-1")
        assert result["data"]["deleted"] is True
        await api.close()
