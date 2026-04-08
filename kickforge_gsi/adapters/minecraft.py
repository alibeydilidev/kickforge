"""
Minecraft RCON adapter.

Uses the ``mcrcon`` library to send commands to a Minecraft
Java Edition server via the RCON protocol.

Supports: summon, give, kill, tp, effect, fill, weather, time, say,
and any arbitrary server command.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("kickforge.gsi.minecraft")

try:
    from mcrcon import MCRcon  # type: ignore[import-untyped]
    _HAS_MCRCON = True
except ImportError:
    _HAS_MCRCON = False


class MinecraftRCONAdapter:
    """
    GameAdapter implementation for Minecraft Java Edition RCON.

    Usage:
        adapter = MinecraftRCONAdapter(host="localhost", port=25575, password="secret")
        await adapter.connect()
        result = await adapter.execute("say Hello from KickForge!", {})
        await adapter.disconnect()
    """

    name = "minecraft"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 25575,
        password: str = "",
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._rcon: Optional[Any] = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to the Minecraft RCON server with retry logic."""
        if not _HAS_MCRCON:
            raise ImportError(
                "mcrcon is required for Minecraft adapter. "
                "Install with: pip install kickforge[minecraft]"
            )

        for attempt in range(1, self.max_retries + 1):
            try:
                self._rcon = MCRcon(self.host, self.password, port=self.port)
                self._rcon.connect()
                self._connected = True
                logger.info(
                    "Connected to Minecraft RCON at %s:%d", self.host, self.port
                )
                return
            except Exception as exc:
                logger.warning(
                    "RCON connect attempt %d/%d failed: %s",
                    attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise ConnectionError(
                        f"Failed to connect to Minecraft RCON after {self.max_retries} attempts"
                    ) from exc

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        """
        Send a command to the Minecraft server.

        Args:
            action: The full command string (e.g. "summon creeper ~ ~5 ~").
            params: Unused for Minecraft; template vars are pre-substituted.

        Returns:
            Server response text.
        """
        if not self._connected or not self._rcon:
            raise ConnectionError("Not connected to Minecraft RCON")

        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(None, self._rcon.command, action)
            logger.debug("RCON command '%s' -> %s", action, response)
            return response or ""
        except Exception:
            logger.exception("RCON command failed: %s", action)
            # Try to reconnect once
            try:
                await self.connect()
                response = await loop.run_in_executor(None, self._rcon.command, action)
                return response or ""
            except Exception:
                raise

    async def get_state(self) -> dict[str, Any]:
        """Query server state via the /list command."""
        if not self._connected:
            return {"connected": False}
        try:
            result = await self.execute("list", {})
            return {"connected": True, "players_raw": result}
        except Exception:
            return {"connected": False, "error": "Failed to query state"}

    async def disconnect(self) -> None:
        """Close the RCON connection."""
        if self._rcon:
            try:
                self._rcon.disconnect()
            except Exception:
                pass
            self._rcon = None
        self._connected = False
        logger.info("Disconnected from Minecraft RCON")

    @property
    def is_connected(self) -> bool:
        return self._connected
