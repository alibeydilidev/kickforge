"""
Timed recurring messages.

Sends scheduled messages to chat at configurable intervals.
Only fires when the stream is live (if live-check is enabled).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("kickforge.bot.timers")


@dataclass
class TimedMessage:
    """A single recurring message."""

    message: str
    interval: float  # seconds
    only_when_live: bool = True


class TimerManager:
    """
    Manages asyncio background tasks for recurring chat messages.

    Usage:
        mgr = TimerManager(send_func=my_send, is_live_func=my_check)
        mgr.add("Don't forget to follow!", interval=900)
        await mgr.start()
        ...
        await mgr.stop()
    """

    def __init__(
        self,
        send_func: Callable[[str], Coroutine[Any, Any, None]],
        is_live_func: Optional[Callable[[], Coroutine[Any, Any, bool]]] = None,
    ) -> None:
        self._send = send_func
        self._is_live = is_live_func
        self._messages: list[TimedMessage] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    def add(
        self,
        message: str,
        interval: float,
        only_when_live: bool = True,
    ) -> None:
        """Add a timed message."""
        self._messages.append(
            TimedMessage(message=message, interval=interval, only_when_live=only_when_live)
        )

    def load_from_config(self, config_list: list[dict[str, Any]]) -> None:
        """Load timed messages from a YAML config list."""
        for entry in config_list:
            self.add(
                message=entry["message"],
                interval=entry.get("interval", 900),
                only_when_live=entry.get("only_when_live", True),
            )

    async def start(self) -> None:
        """Start all timer background tasks."""
        if self._running:
            return
        self._running = True
        for tm in self._messages:
            task = asyncio.create_task(self._timer_loop(tm))
            self._tasks.append(task)
        logger.info("Started %d timed message(s)", len(self._tasks))

    async def stop(self) -> None:
        """Cancel all timer tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Stopped all timed messages")

    async def _timer_loop(self, tm: TimedMessage) -> None:
        """Background loop for a single timed message."""
        try:
            while self._running:
                await asyncio.sleep(tm.interval)
                if not self._running:
                    break

                # Check if live
                if tm.only_when_live and self._is_live:
                    try:
                        live = await self._is_live()
                        if not live:
                            continue
                    except Exception:
                        logger.debug("Live check failed, skipping timed message")
                        continue

                try:
                    await self._send(tm.message)
                    logger.debug("Sent timed message: %s", tm.message[:50])
                except Exception:
                    logger.exception("Failed to send timed message")
        except asyncio.CancelledError:
            pass

    @property
    def message_count(self) -> int:
        """Number of registered timed messages."""
        return len(self._messages)
