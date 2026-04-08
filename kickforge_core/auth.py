"""
Kick OAuth 2.1 authentication.

Handles:
- Client credentials flow (bot access)
- Authorization code flow (user access)
- Automatic token refresh
- Token caching with TTL
"""

from __future__ import annotations

import time
import logging
import secrets
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

import httpx

from kickforge_core.exceptions import AuthenticationError, TokenExpiredError

logger = logging.getLogger("kickforge.auth")

KICK_TOKEN_URL = "https://id.kick.com/oauth/token"
KICK_AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
KICK_REVOKE_URL = "https://id.kick.com/oauth/revoke"


@dataclass
class TokenPair:
    """Stores access + refresh tokens with expiry tracking."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: float = 0.0
    token_type: str = "Bearer"
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 60s safety margin)."""
        return time.time() >= (self.expires_at - 60)


@dataclass
class KickAuth:
    """
    Manages Kick OAuth 2.1 authentication.

    Usage:
        auth = KickAuth(client_id="...", client_secret="...")

        # Bot access (no user interaction needed)
        token = await auth.get_app_token()

        # User access (requires redirect flow)
        url = auth.get_authorize_url(redirect_uri="...", scopes=[...])
        token = await auth.exchange_code(code="...", redirect_uri="...")
    """

    client_id: str
    client_secret: str
    _tokens: dict[str, TokenPair] = field(default_factory=dict)
    _http: Optional[httpx.AsyncClient] = field(default=None, repr=False)

    async def _client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _token_request(self, data: dict[str, str]) -> dict[str, object]:
        """Execute a token request and handle errors."""
        client = await self._client()
        try:
            response = await client.post(KICK_TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise AuthenticationError(f"Token request failed: {exc}") from exc

        if response.status_code != 200:
            try:
                detail = response.json().get("error_description", response.text)
            except Exception:
                detail = response.text
            raise AuthenticationError(
                f"Token request returned {response.status_code}: {detail}"
            )

        return response.json()

    async def get_app_token(self) -> str:
        """Get a bot/app access token via client credentials flow."""
        cache_key = "app"
        cached = self._tokens.get(cache_key)
        if cached and not cached.is_expired:
            return cached.access_token

        data = await self._token_request({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })

        token_pair = TokenPair(
            access_token=str(data["access_token"]),
            expires_at=time.time() + float(data.get("expires_in", 3600)),
            token_type=str(data.get("token_type", "Bearer")),
            scope=str(data.get("scope", "")),
        )
        self._tokens[cache_key] = token_pair
        logger.info("Obtained app access token (expires in %ss)", data.get("expires_in", 3600))
        return token_pair.access_token

    def get_authorize_url(
        self,
        redirect_uri: str,
        scopes: list[str],
        state: Optional[str] = None,
    ) -> str:
        """Build the OAuth authorization URL for user consent."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state or secrets.token_urlsafe(32),
        }
        return f"{KICK_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenPair:
        """Exchange an authorization code for user tokens."""
        data = await self._token_request({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        })

        token_pair = TokenPair(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
            expires_at=time.time() + float(data.get("expires_in", 3600)),
            token_type=str(data.get("token_type", "Bearer")),
            scope=str(data.get("scope", "")),
        )
        self._tokens["user"] = token_pair
        logger.info("Exchanged auth code for user token")
        return token_pair

    async def refresh_user_token(self) -> str:
        """Refresh the user access token."""
        token_pair = self._tokens.get("user")
        if not token_pair or not token_pair.refresh_token:
            raise TokenExpiredError(
                "No user token or refresh token available. Run exchange_code first."
            )

        data = await self._token_request({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": token_pair.refresh_token,
        })

        new_pair = TokenPair(
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token", token_pair.refresh_token)),
            expires_at=time.time() + float(data.get("expires_in", 3600)),
            token_type=str(data.get("token_type", "Bearer")),
            scope=str(data.get("scope", "")),
        )
        self._tokens["user"] = new_pair
        logger.info("Refreshed user token")
        return new_pair.access_token

    async def revoke_token(self, token: str) -> None:
        """Revoke an access or refresh token."""
        client = await self._client()
        try:
            response = await client.post(
                KICK_REVOKE_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "token": token,
                },
            )
            if response.status_code == 200:
                logger.info("Token revoked successfully")
            else:
                logger.warning("Token revocation returned %d", response.status_code)
        except httpx.HTTPError:
            logger.exception("Failed to revoke token")

    async def get_valid_token(self, token_type: str = "app") -> str:
        """Get a valid (non-expired) token, refreshing if necessary."""
        if token_type == "app":
            return await self.get_app_token()

        token_pair = self._tokens.get("user")
        if not token_pair:
            raise TokenExpiredError("No user token. Call exchange_code first.")
        if token_pair.is_expired:
            return await self.refresh_user_token()
        return token_pair.access_token

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
