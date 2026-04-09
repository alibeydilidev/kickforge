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
import re
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
            # Log full response body to aid debugging
            body_text = response.text or "<empty>"
            logger.warning(
                "Kick API %d on %s %s (token=%s)\n  Response body: %s",
                response.status_code,
                method,
                endpoint,
                token_type,
                body_text[:500],
            )
            try:
                body_json = response.json()
                detail = body_json.get("message") or body_json.get("error") or body_text
            except Exception:
                detail = body_text
            # Extra hint for 401 on chat endpoint
            if response.status_code == 401 and "/chat" in endpoint:
                detail = (
                    f"{detail} — Kick requires a USER access token with chat:write scope. "
                    "App tokens (client credentials) cannot send chat messages."
                )
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
        poster_type: str = "user",
        reply_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send a chat message to a channel.

        NOTE: Kick's chat API requires a USER access token with
        ``chat:write`` scope for ALL send operations, even when
        ``poster_type="bot"``.  App tokens (client credentials)
        always return 401.

        Args:
            broadcaster_id: The broadcaster's user ID. When ``poster_type="bot"``
                this is ignored by Kick (the bot posts to its own channel).
            content: Message text (max 500 chars).
            poster_type: "user" (default) or "bot".
            reply_to: Optional message ID to reply to.
        """
        payload: dict[str, Any] = {
            "content": content[:500],
            "type": poster_type,
        }
        # Kick ignores broadcaster_user_id when type=bot but accepts it
        if poster_type == "user":
            payload["broadcaster_user_id"] = broadcaster_id
        if reply_to:
            payload["reply_to_message_id"] = reply_to

        result = await self._request(
            "POST", "/public/v1/chat", token_type="user", json=payload
        )
        logger.debug("Sent message to broadcaster %d: %s", broadcaster_id, content[:50])
        return result

    # -----------------------------------------------------------------------
    # Channels
    # -----------------------------------------------------------------------

    async def get_channel(self, slug: str) -> dict[str, Any]:
        """Get channel information by slug (username)."""
        return await self._request("GET", "/public/v1/channels", params={"slug": slug})

    async def get_chatroom_id(
        self,
        slug: str,
        channel_data: Optional[dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        Resolve a channel slug to its Pusher chatroom_id.

        Tries, in order:
        1. The official ``/public/v1/channels`` response (usually doesn't
           include chatroom_id, but some endpoints do).
        2. The unauthenticated ``kick.com/api/v2/channels/{slug}``
           endpoint with a browser User-Agent.
        3. Scraping the ``kick.com/{slug}`` HTML page — the chatroom ID
           is embedded in a Next.js data block.

        Args:
            slug: Channel slug.
            channel_data: Pre-fetched response from ``get_channel()`` to
                avoid a duplicate API call.

        Returns None if every method fails.
        """
        # 1) Try the pre-fetched public API response
        if channel_data is None:
            try:
                channel_data = await self.get_channel(slug)
            except Exception:
                logger.debug("Public channel lookup failed")
                channel_data = None

        if isinstance(channel_data, dict):
            entries = channel_data.get("data", [channel_data])
            entry = entries[0] if isinstance(entries, list) and entries else entries
            if isinstance(entry, dict):
                chatroom = entry.get("chatroom") or {}
                if isinstance(chatroom, dict) and chatroom.get("id"):
                    return int(chatroom["id"])
                if entry.get("chatroom_id"):
                    return int(entry["chatroom_id"])

        # Browser-ish headers to get past Cloudflare bot detection
        browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 2) Legacy unauthenticated JSON endpoint
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=True
            ) as client:
                response = await client.get(
                    f"https://kick.com/api/v2/channels/{slug}",
                    headers=browser_headers,
                )
                if response.status_code == 200:
                    data = response.json()
                    chatroom = data.get("chatroom") or {}
                    if chatroom.get("id"):
                        logger.info("Resolved chatroom_id from kick.com/api/v2")
                        return int(chatroom["id"])
                else:
                    logger.debug(
                        "kick.com/api/v2 returned %d (likely Cloudflare)",
                        response.status_code,
                    )
        except Exception:
            logger.debug("Legacy API chatroom lookup failed", exc_info=True)

        # 3) Scrape the channel HTML page
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=True
            ) as client:
                html_headers = {
                    **browser_headers,
                    "Accept": "text/html,application/xhtml+xml",
                }
                response = await client.get(
                    f"https://kick.com/{slug}",
                    headers=html_headers,
                )
                if response.status_code == 200:
                    chatroom_id = _extract_chatroom_id_from_html(response.text)
                    if chatroom_id:
                        logger.info("Resolved chatroom_id from HTML page scrape")
                        return chatroom_id
                else:
                    logger.debug(
                        "Channel HTML page returned %d", response.status_code
                    )
        except Exception:
            logger.debug("HTML scrape chatroom lookup failed", exc_info=True)

        return None

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


# ---------------------------------------------------------------------------
# HTML scraping helper
# ---------------------------------------------------------------------------

# Kick embeds channel data as JSON in the page HTML. The chatroom_id
# shows up as `"chatroom":{"id":12345` or `"chatroom_id":12345`.
_CHATROOM_PATTERNS = [
    re.compile(r'"chatroom"\s*:\s*\{\s*"id"\s*:\s*(\d+)'),
    re.compile(r'"chatroom_id"\s*:\s*(\d+)'),
    re.compile(r'\\"chatroom\\"\s*:\s*\{\s*\\"id\\"\s*:\s*(\d+)'),
    re.compile(r'\\"chatroom_id\\"\s*:\s*(\d+)'),
]


def _extract_chatroom_id_from_html(html: str) -> Optional[int]:
    """Find the first chatroom id embedded in a Kick channel HTML page."""
    for pattern in _CHATROOM_PATTERNS:
        match = pattern.search(html)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None
