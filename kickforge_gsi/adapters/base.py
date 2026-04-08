"""
Abstract GameAdapter interface.

Every game adapter (Minecraft RCON, CS2, FiveM, custom HTTP)
implements this interface so the bridge and tier engine can
drive any game uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GameAdapter(ABC):
    """
    Abstract base class for game adapters.

    Subclass this to integrate a new game with KickForge.
    The bridge will call connect() once at startup, then
    execute() for every matched tier action, and disconnect()
    on shutdown.
    """

    name: str = "base"

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the game server."""

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> str:
        """
        Execute a game action.

        Args:
            action: The raw command string (e.g. "summon creeper ~ ~5 ~").
            params: Template variables (user, amount, etc.) already substituted
                    in ``action``, but available here for adapters that need them.

        Returns:
            Response string from the game server.
        """

    @abstractmethod
    async def get_state(self) -> dict[str, Any]:
        """
        Return the current game state as a dict.

        What this contains depends on the adapter:
        - Minecraft: online players, TPS, etc.
        - CS2 GSI: player HP, armor, score, etc.
        - Generic HTTP: last response body.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the game server."""

    @property
    def is_connected(self) -> bool:  # noqa: D401
        """Whether the adapter currently has an active connection."""
        return False
