"""
Heat moment detection.

Monitors chat velocity via the EventBus and fires a ``heat_moment``
event when the weighted heat score exceeds a configurable threshold.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from kickforge_core.events import ChatMessageEvent, EventBus

logger = logging.getLogger("kickforge.clip.detector")


@dataclass
class HeatMoment:
    """A detected hype moment."""

    timestamp: float
    score: float
    messages_per_second: float
    unique_chatters: int


@dataclass
class HeatConfig:
    """Configuration for the heat detector."""

    window_seconds: float = 60.0
    threshold: float = 5.0
    weight_mps: float = 1.0       # messages-per-second weight
    weight_chatters: float = 0.5  # unique-chatters weight
    cooldown_seconds: float = 30.0  # min time between heat events
    poll_interval: float = 2.0     # how often to recalculate


HeatCallback = Callable[[HeatMoment], Coroutine[Any, Any, None]]


class HeatDetector:
    """
    Sliding-window heat detector.

    Attaches to an EventBus, tracks chat velocity, and fires callbacks
    when the heat score exceeds the threshold.

    Usage:
        detector = HeatDetector(bus, config=HeatConfig(threshold=3.0))

        @detector.on_heat
        async def handle(moment: HeatMoment):
            print(f"Hype at {moment.timestamp}! Score={moment.score:.1f}")

        await detector.start()
    """

    def __init__(
        self,
        bus: EventBus,
        config: Optional[HeatConfig] = None,
    ) -> None:
        self.bus = bus
        self.config = config or HeatConfig()
        self._messages: deque[tuple[float, int]] = deque()  # (timestamp, user_id)
        self._callbacks: list[HeatCallback] = []
        self._task: Optional[asyncio.Task[None]] = None
        self._last_heat: float = 0.0
        self._running = False
        self._registered = False

    def on_heat(self, func: HeatCallback) -> HeatCallback:
        """Decorator to register a heat-moment callback."""
        self._callbacks.append(func)
        return func

    def _register_bus(self) -> None:
        if self._registered:
            return

        @self.bus.on("chat.message.sent")
        async def _on_chat(event: ChatMessageEvent) -> None:
            sender = event.sender
            uid = sender.user_id if sender else 0
            self._messages.append((time.time(), uid))

        self._registered = True

    async def start(self) -> None:
        """Start the background heat-check loop."""
        self._register_bus()
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("HeatDetector started (threshold=%.1f)", self.config.threshold)

    async def stop(self) -> None:
        """Stop the detector."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("HeatDetector stopped")

    def compute_score(self) -> tuple[float, float, int]:
        """
        Compute the current heat score.

        Returns:
            (score, messages_per_second, unique_chatters)
        """
        now = time.time()
        cutoff = now - self.config.window_seconds

        # Prune old messages
        while self._messages and self._messages[0][0] < cutoff:
            self._messages.popleft()

        if not self._messages:
            return 0.0, 0.0, 0

        elapsed = now - self._messages[0][0] if len(self._messages) > 1 else self.config.window_seconds
        elapsed = max(elapsed, 1.0)

        mps = len(self._messages) / elapsed
        unique = len({uid for _, uid in self._messages})

        score = (mps * self.config.weight_mps) + (unique * self.config.weight_chatters)
        return score, mps, unique

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.config.poll_interval)
                if not self._running:
                    break

                score, mps, unique = self.compute_score()
                if score < self.config.threshold:
                    continue

                now = time.time()
                if now - self._last_heat < self.config.cooldown_seconds:
                    continue

                self._last_heat = now
                moment = HeatMoment(
                    timestamp=now,
                    score=score,
                    messages_per_second=mps,
                    unique_chatters=unique,
                )
                logger.info(
                    "Heat moment! score=%.1f mps=%.1f chatters=%d",
                    score, mps, unique,
                )
                for cb in self._callbacks:
                    try:
                        await cb(moment)
                    except Exception:
                        logger.exception("Heat callback raised")

                # Also emit on the event bus
                from kickforge_core.events import Event
                await self.bus.emit("heat_moment", Event(
                    event_type="heat_moment",
                    raw={"score": score, "mps": mps, "unique_chatters": unique},
                ))
        except asyncio.CancelledError:
            pass

    @property
    def moments(self) -> list[HeatMoment]:
        """Return list of all detected moments (for post-stream use)."""
        return []  # Caller should collect via callback; kept for interface compat
