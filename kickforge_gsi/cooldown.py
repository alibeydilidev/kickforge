"""
Per-action and per-user cooldown manager.

Thread-safe via asyncio.Lock.  Returns remaining seconds
when a cooldown is active so callers can inform the user.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional


class CooldownManager:
    """
    Manages per-action global cooldowns and optional per-user cooldowns.

    Usage:
        cd = CooldownManager()
        remaining = await cd.check("chicken_army")        # global
        remaining = await cd.check("chicken_army", uid=5)  # per-user
        if remaining > 0:
            print(f"On cooldown for {remaining:.0f}s")
        else:
            await cd.trigger("chicken_army", cooldown=30)
            await cd.trigger("chicken_army", cooldown=10, user_id=5)
    """

    def __init__(self) -> None:
        self._global: dict[str, float] = {}  # action -> expires_at
        self._user: dict[str, float] = {}    # "action:uid" -> expires_at
        self._lock = asyncio.Lock()

    async def check(
        self,
        action: str,
        user_id: Optional[int] = None,
    ) -> float:
        """
        Check if an action is on cooldown.

        Args:
            action: Action name.
            user_id: If given, also check per-user cooldown.

        Returns:
            Remaining seconds (0.0 if not on cooldown).
        """
        async with self._lock:
            now = time.time()
            # Global check
            g_remaining = max(0.0, self._global.get(action, 0.0) - now)
            if g_remaining > 0:
                return g_remaining

            # Per-user check
            if user_id is not None:
                key = f"{action}:{user_id}"
                u_remaining = max(0.0, self._user.get(key, 0.0) - now)
                if u_remaining > 0:
                    return u_remaining

            return 0.0

    async def trigger(
        self,
        action: str,
        cooldown: float,
        user_id: Optional[int] = None,
    ) -> None:
        """
        Start a cooldown for an action.

        Args:
            action: Action name.
            cooldown: Duration in seconds.
            user_id: If given, set per-user cooldown instead of global.
        """
        async with self._lock:
            expires = time.time() + cooldown
            if user_id is not None:
                self._user[f"{action}:{user_id}"] = expires
            else:
                self._global[action] = expires

    async def reset(self, action: str, user_id: Optional[int] = None) -> None:
        """Clear a cooldown."""
        async with self._lock:
            if user_id is not None:
                self._user.pop(f"{action}:{user_id}", None)
            else:
                self._global.pop(action, None)

    async def reset_all(self) -> None:
        """Clear every cooldown."""
        async with self._lock:
            self._global.clear()
            self._user.clear()
