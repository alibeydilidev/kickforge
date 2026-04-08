"""
CS2 Source RCON adapter (write).

Implements the Valve Source RCON protocol over TCP.
This is distinct from Minecraft RCON — packets use
little-endian int32 framing and a different auth handshake.

Only works on community / dedicated servers (not matchmaking).
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any, Optional

logger = logging.getLogger("kickforge.gsi.cs2_rcon")

# Source RCON packet types
SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


def _pack_rcon_packet(request_id: int, packet_type: int, body: str) -> bytes:
    """Build a Source RCON packet (little-endian)."""
    body_bytes = body.encode("utf-8") + b"\x00\x00"
    size = 4 + 4 + len(body_bytes)  # id(4) + type(4) + body+padding
    return struct.pack("<iii", size, request_id, packet_type) + body_bytes


def _unpack_rcon_packet(data: bytes) -> tuple[int, int, str]:
    """Parse a Source RCON response body (after size prefix). Returns (request_id, type, body)."""
    if len(data) < 8:
        raise ValueError("RCON packet too short")
    request_id, packet_type = struct.unpack("<ii", data[:8])
    body = data[8:]
    return request_id, packet_type, body.rstrip(b"\x00").decode("utf-8", errors="replace")


class CS2RCONAdapter:
    """
    Source RCON adapter for CS2 dedicated / community servers.

    Usage:
        adapter = CS2RCONAdapter(host="192.168.1.10", port=27015, password="rconpw")
        await adapter.connect()
        resp = await adapter.execute("sv_gravity 200", {})
        await adapter.disconnect()
    """

    name = "cs2_rcon"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 27015,
        password: str = "",
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._request_id = 0
        self._lock = asyncio.Lock()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def connect(self) -> None:
        """Open TCP connection and authenticate via Source RCON."""
        for attempt in range(1, self.max_retries + 1):
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.timeout,
                )
                await self._authenticate()
                self._connected = True
                logger.info("Connected to CS2 RCON at %s:%d", self.host, self.port)
                return
            except Exception as exc:
                logger.warning(
                    "RCON connect attempt %d/%d failed: %s",
                    attempt, self.max_retries, exc,
                )
                await self._close_transport()
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise ConnectionError(
                        f"Failed to connect to CS2 RCON after {self.max_retries} attempts"
                    ) from exc

    async def _authenticate(self) -> None:
        """Send the RCON auth packet and validate the response."""
        auth_id = self._next_id()
        packet = _pack_rcon_packet(auth_id, SERVERDATA_AUTH, self.password)
        self._writer.write(packet)  # type: ignore[union-attr]
        await self._writer.drain()  # type: ignore[union-attr]

        # Server sends an empty SERVERDATA_RESPONSE_VALUE, then AUTH_RESPONSE
        _ = await self._read_packet()  # empty ack
        rid, ptype, _ = await self._read_packet()

        if rid == -1:
            raise PermissionError("RCON authentication failed — wrong password")
        logger.debug("RCON authentication successful (id=%d)", rid)

    async def _read_packet(self) -> tuple[int, int, str]:
        """Read one RCON response packet from the TCP stream."""
        reader = self._reader
        if reader is None:
            raise ConnectionError("Not connected")

        size_data = await asyncio.wait_for(reader.readexactly(4), timeout=self.timeout)
        (size,) = struct.unpack("<i", size_data)
        body_data = await asyncio.wait_for(reader.readexactly(size), timeout=self.timeout)

        request_id, packet_type = struct.unpack("<ii", body_data[:8])
        body = body_data[8:].rstrip(b"\x00").decode("utf-8", errors="replace")
        return request_id, packet_type, body

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        """
        Send a console command to the CS2 server.

        Args:
            action: The command string (e.g. "sv_gravity 200").
            params: Unused — template vars are pre-substituted.

        Returns:
            Server response text.
        """
        if not self._connected:
            raise ConnectionError("Not connected to CS2 RCON")

        async with self._lock:
            rid = self._next_id()
            packet = _pack_rcon_packet(rid, SERVERDATA_EXECCOMMAND, action)

            try:
                self._writer.write(packet)  # type: ignore[union-attr]
                await self._writer.drain()  # type: ignore[union-attr]
                _, _, body = await self._read_packet()
                logger.debug("RCON '%s' -> %s", action, body[:200])
                return body
            except Exception:
                logger.exception("RCON execute failed: %s", action)
                self._connected = False
                raise

    async def get_state(self) -> dict[str, Any]:
        """Query basic server state."""
        if not self._connected:
            return {"connected": False}
        try:
            status = await self.execute("status", {})
            return {"connected": True, "status_raw": status}
        except Exception:
            return {"connected": False, "error": "Failed to query state"}

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        await self._close_transport()
        self._connected = False
        logger.info("Disconnected from CS2 RCON")

    async def _close_transport(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    @property
    def is_connected(self) -> bool:
        return self._connected
