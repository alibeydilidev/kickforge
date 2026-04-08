"""
Kick REST API client.

Wraps the public Kick API endpoints for:
- Sending chat messages (as bot or user)
- Channel information
- Moderation actions (ban, timeout)
- Event subscriptions (webhooks)
- Livestream info
- Kicks leaderboard
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from kickforge_core.auth import KickAuth
from kickforge_core.exceptions import APIError, RateLimitError

logger = logging.getLogger("kickforge.api")

KICK_API_BASE = "https://api.kick.com"


class KickAPI:
    """
    High-level Kick API client.

    Usage:
        auth = KickAuth(client_id="...", client_secret="...")
        api = KickAPI(auth=auth)

        await api.send_message(broadcaster_id=12345, content="Hello from KickForge!")
        channel = await api.get_channel("yargitay")
    """

    def __init__(self, auth: KickAuth) -> None:
        self.auth = auth
        self._http: Optional[httpx.AsyncClient] = None

    async def _client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=KICK_API_BASE,
                timeout=30.0,
            )
        return self._http

    async def _headers(self, token_type: str = "app") -> dict[str, str]:
        """Build auth headers."""
        token = await self.auth.get_valid_token(token_type)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        token_type: str = "app",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute an API request with error handling."""
        client = await self._client()
        headers = await self._headers(token_type)

        try:
            response = await client.request(method, endpoint, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise APIError(0, str(exc), endpoint) from exc

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "60"))
            raise RateLimitError(retry_after=retry_after, endpoint=endpoint)

        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, str(detail), endpoint)

        if response.status_code == 204:
            return {}

        return response.json()

    # -----------------------------------------------------------------------
    # Chat
    # -----------------------------------------------------------------------

    async def send_message(
        self,
        broadcaster_id: int,
        content: str,
        poster_type: str = "bot",
        reply_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send a chat message to a channel.

        Args:
            broadcaster_id: The broadcaster's user ID.
            content: Message text (max 500 chars).
            poster_type: "bot" or "user".
            reply_to: Optional message ID to reply to.
        """
        payload: dict[str, Any] = {
            "broadcaster_user_id": broadcaster_id,
            "content": content[:500],
            "type": poster_type,
        }
        if reply_to:
            payload["reply_to"] = {"message_id": reply_to}

        token_type = "app" if poster_type == "bot" else "user"
        result = await self._request("POST", "/public/v1/chat", token_type=token_type, json=payload)
        logger.debug("Sent message to broadcaster %d: %s", broadcaster_id, content[:50])
        return result

    # -----------------------------------------------------------------------
    # Channels
    # -----------------------------------------------------------------------

    async def get_channel(self, slug: str) -> dict[str, Any]:
        """Get channel information by slug (username)."""
        return await self._request("GET", "/public/v1/channels", params={"slug": slug})

    async def get_livestream(self, broadcaster_id: int) -> dict[str, Any]:
        """Get current livestream info for a broadcaster."""
        return await self._request(
            "GET", "/public/v1/livestreams", params={"broadcaster_user_id": broadcaster_id}
        )

    # -----------------------------------------------------------------------
    # Moderation
    # -----------------------------------------------------------------------

    async def ban_user(
        self,
        broadcaster_id: int,
        user_id: int,
        duration: Optional[int] = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Ban or timeout a user.

        Args:
            broadcaster_id: Channel to ban from.
            user_id: User to ban.
            duration: Timeout seconds (None = permanent ban).
            reason: Optional reason string.
        """
        payload: dict[str, Any] = {
            "broadcaster_user_id": broadcaster_id,
            "user_id": user_id,
            "reason": reason,
        }
        if duration is not None:
            payload["duration"] = duration

        result = await self._request(
            "POST", "/public/v1/moderation/bans", token_type="user", json=payload
        )
        logger.info("Banned user %d from channel %d (duration=%s)", user_id, broadcaster_id, duration)
        return result

    async def unban_user(self, broadcaster_id: int, user_id: int) -> dict[str, Any]:
        """Unban a user from a channel."""
        return await self._request(
            "DELETE",
            "/public/v1/moderation/bans",
            token_type="user",
            params={"broadcaster_user_id": broadcaster_id, "user_id": user_id},
        )

    async def delete_message(self, message_id: str) -> dict[str, Any]:
        """Delete a chat message by ID."""
        return await self._request(
            "DELETE", f"/public/v1/chat/{message_id}", token_type="user"
        )

    # -----------------------------------------------------------------------
    # Event subscriptions (webhooks)
    # -----------------------------------------------------------------------

    async def subscribe_events(
        self,
        events: list[str],
        broadcaster_user_id: int,
        version: int = 1,
    ) -> dict[str, Any]:
        """
        Subscribe to webhook events.

        Args:
            events: List of event type strings.
            broadcaster_user_id: The broadcaster to receive events for.
            version: Event version (default 1).
        """
        payload: dict[str, Any] = {
            "events": [{"name": e, "version": version} for e in events],
            "method": "webhook",
            "broadcaster_user_id": broadcaster_user_id,
        }
        result = await self._request("POST", "/public/v1/events/subscriptions", json=payload)
        logger.info("Subscribed to events: %s (broadcaster=%d)", events, broadcaster_user_id)
        return result

    async def get_subscriptions(self) -> dict[str, Any]:
        """List all active event subscriptions."""
        return await self._request("GET", "/public/v1/events/subscriptions")

    async def delete_subscriptions(self, ids: list[str]) -> dict[str, Any]:
        """
        Delete event subscriptions by ID.

        Args:
            ids: List of subscription IDs to remove.
        """
        params = [("id", sid) for sid in ids]
        result = await self._request(
            "DELETE", "/public/v1/events/subscriptions", params=params
        )
        logger.info("Deleted %d subscription(s)", len(ids))
        return result

    # -----------------------------------------------------------------------
    # Kicks leaderboard
    # -----------------------------------------------------------------------

    async def get_kicks_leaderboard(self, broadcaster_id: int) -> dict[str, Any]:
        """Get the kicks (gifting) leaderboard for a channel."""
        return await self._request(
            "GET",
            "/public/v1/kicks/leaderboard",
            params={"broadcaster_user_id": broadcaster_id},
        )

    async def close(self) -> None:
        """Close the HTTP client and auth client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        await self.auth.close()
