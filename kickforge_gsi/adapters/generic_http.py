"""
Generic HTTP adapter.

Sends commands via HTTP POST/GET to any game server with an
HTTP API (FiveM, custom game servers, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("kickforge.gsi.generic_http")


class GenericHTTPAdapter:
    """
    Adapter that sends game actions via HTTP requests.

    Usage:
        adapter = GenericHTTPAdapter(
            base_url="http://localhost:30120",
            method="POST",
            headers={"Authorization": "Bearer token"},
        )
        await adapter.connect()
        resp = await adapter.execute("/api/command", {"command": "spawn_car"})
        await adapter.disconnect()
    """

    name = "generic_http"

    def __init__(
        self,
        base_url: str,
        method: str = "POST",
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.method = method.upper()
        self.default_headers = headers or {}
        self.timeout = timeout
        self._http: Optional[httpx.AsyncClient] = None
        self._last_response: dict[str, Any] = {}
        self._connected = False

    async def connect(self) -> None:
        """Create the HTTP client."""
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.default_headers,
            timeout=self.timeout,
        )
        self._connected = True
        logger.info("Generic HTTP adapter connected to %s", self.base_url)

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        """
        Send an HTTP request.

        Args:
            action: URL path or full endpoint (e.g. "/api/run").
            params: Sent as JSON body (POST/PUT) or query params (GET).

        Returns:
            Response body as string.
        """
        if not self._http or not self._connected:
            raise ConnectionError("HTTP adapter not connected")

        try:
            if self.method in ("POST", "PUT", "PATCH"):
                response = await self._http.request(self.method, action, json=params)
            else:
                response = await self._http.request(self.method, action, params=params)

            response.raise_for_status()
            self._last_response = {
                "status": response.status_code,
                "body": response.text,
            }
            logger.debug(
                "HTTP %s %s -> %d", self.method, action, response.status_code
            )
            return response.text
        except httpx.HTTPError as exc:
            logger.exception("HTTP request failed: %s %s", self.method, action)
            raise ConnectionError(f"HTTP request failed: {exc}") from exc

    async def get_state(self) -> dict[str, Any]:
        """Return the last HTTP response."""
        return {
            "connected": self._connected,
            "base_url": self.base_url,
            "last_response": self._last_response,
        }

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None
        self._connected = False
        logger.info("Generic HTTP adapter disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected
