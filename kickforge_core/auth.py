"""
Kick OAuth 2.1 authentication.

Handles:
- Client credentials flow (app/bot access)
- Authorization code flow + PKCE (user access)
- Automatic token refresh
- Token caching in memory + persistence to ~/.kickforge/tokens.json
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

from kickforge_core.exceptions import AuthenticationError, TokenExpiredError

logger = logging.getLogger("kickforge.auth")

KICK_TOKEN_URL = "https://id.kick.com/oauth/token"
KICK_AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
KICK_REVOKE_URL = "https://id.kick.com/oauth/revoke"

# Where saved user tokens live.
TOKEN_FILE: Path = Path.home() / ".kickforge" / "tokens.json"


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate a PKCE verifier/challenge pair using the S256 method.

    Returns:
        (code_verifier, code_challenge) — verifier is a random
        43-128 char URL-safe string, challenge is the SHA-256
        of the verifier, URL-safe base64 encoded without padding.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


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

    def to_dict(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TokenPair:
        return cls(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
            expires_at=float(data.get("expires_at", 0.0)),  # type: ignore[arg-type]
            token_type=str(data.get("token_type", "Bearer")),
            scope=str(data.get("scope", "")),
        )


@dataclass
class KickAuth:
    """
    Manages Kick OAuth 2.1 authentication.

    Usage:
        auth = KickAuth(client_id="...", client_secret="...")

        # App/bot access (no user interaction needed)
        token = await auth.get_app_token()

        # User access (requires redirect flow with PKCE)
        verifier, challenge = generate_pkce_pair()
        url = auth.get_authorize_url(
            redirect_uri="...", scopes=[...], code_challenge=challenge
        )
        # user visits url, authorizes, comes back with code
        await auth.exchange_code(code="...", redirect_uri="...", code_verifier=verifier)
    """

    client_id: str
    client_secret: str
    token_file: Optional[Path] = None
    _tokens: dict[str, TokenPair] = field(default_factory=dict)
    _http: Optional[httpx.AsyncClient] = field(default=None, repr=False)
    _user_token_loaded_from_disk: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.token_file is None:
            self.token_file = TOKEN_FILE

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
        code_challenge: Optional[str] = None,
        code_challenge_method: str = "S256",
    ) -> str:
        """
        Build the OAuth authorization URL for user consent.

        Kick OAuth 2.1 requires PKCE — pass the ``code_challenge`` from
        ``generate_pkce_pair()`` and store the verifier for the token
        exchange step.
        """
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state or secrets.token_urlsafe(32),
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method
        return f"{KICK_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
    ) -> TokenPair:
        """
        Exchange an authorization code for user tokens.

        Pass ``code_verifier`` from the PKCE pair used in the
        authorization URL.
        """
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        data = await self._token_request(payload)

        token_pair = TokenPair(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
            expires_at=time.time() + float(data.get("expires_in", 3600)),
            token_type=str(data.get("token_type", "Bearer")),
            scope=str(data.get("scope", "")),
        )
        self._tokens["user"] = token_pair
        self._save_user_token(token_pair)
        logger.info("Exchanged auth code for user token (scope=%s)", token_pair.scope)
        return token_pair

    async def refresh_user_token(self) -> str:
        """Refresh the user access token."""
        token_pair = self._tokens.get("user")
        if not token_pair:
            # Try loading from disk before giving up
            disk_token = self._load_user_token()
            if disk_token:
                self._tokens["user"] = disk_token
                token_pair = disk_token

        if not token_pair or not token_pair.refresh_token:
            raise TokenExpiredError(
                "No refresh token available. Run 'kickforge auth' to re-authorize."
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
        self._save_user_token(new_pair)
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

        # First access — try loading a persisted token from disk
        if not token_pair and not self._user_token_loaded_from_disk:
            disk_token = self._load_user_token()
            if disk_token:
                self._tokens["user"] = disk_token
                token_pair = disk_token
            self._user_token_loaded_from_disk = True

        if not token_pair:
            raise TokenExpiredError(
                "No user token found. Run 'kickforge auth' to authorize chat sending."
            )
        if token_pair.is_expired:
            return await self.refresh_user_token()
        return token_pair.access_token

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _save_user_token(self, tp: TokenPair) -> None:
        """Persist the user token to disk (chmod 600)."""
        path = self.token_file or TOKEN_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(tp.to_dict(), indent=2))
            try:
                path.chmod(0o600)
            except OSError:
                pass
            logger.debug("User token saved to %s", path)
        except Exception:
            logger.exception("Failed to save user token to %s", path)

    def _load_user_token(self) -> Optional[TokenPair]:
        """Load a persisted user token from disk, if it exists."""
        path = self.token_file or TOKEN_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            tp = TokenPair.from_dict(data)
            logger.info("Loaded saved user token from %s", path)
            return tp
        except Exception:
            logger.exception("Failed to load user token from %s", path)
            return None

    def clear_saved_token(self) -> None:
        """Delete the persisted user token file."""
        path = self.token_file or TOKEN_FILE
        if path.exists():
            try:
                path.unlink()
                logger.info("Deleted saved user token at %s", path)
            except OSError:
                logger.exception("Failed to delete saved user token")
        self._tokens.pop("user", None)
        self._user_token_loaded_from_disk = False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
