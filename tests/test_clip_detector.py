"""Tests for kickforge_clip.detector module."""

import time

import pytest

from kickforge_core.events import ChatMessageEvent, EventBus, Sender
from kickforge_clip.detector import HeatDetector, HeatConfig, HeatMoment


def _make_chat(user_id: int = 1, username: str = "u") -> ChatMessageEvent:
    return ChatMessageEvent(
        event_type="chat.message.sent",
        raw={},
        message_id="m",
        message="msg",
        broadcaster_user_id=99,
        sender=Sender(user_id=user_id, username=username),
    )


class TestHeatDetector:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def detector(self, bus):
        config = HeatConfig(
            window_seconds=10.0,
            threshold=2.0,
            weight_mps=1.0,
            weight_chatters=0.5,
            cooldown_seconds=1.0,
            poll_interval=0.05,
        )
        return HeatDetector(bus=bus, config=config)

    def test_compute_score_empty(self, detector):
        score, mps, unique = detector.compute_score()
        assert score == 0.0
        assert mps == 0.0
        assert unique == 0

    def test_compute_score_with_messages(self, detector):
        now = time.time()
        # Simulate 10 messages from 3 users in the last second
        for i in range(10):
            detector._messages.append((now - 0.1 * i, i % 3 + 1))

        score, mps, unique = detector.compute_score()
        assert mps > 0
        assert unique == 3
        assert score > 0

    @pytest.mark.asyncio
    async def test_bus_registration(self, bus, detector):
        detector._register_bus()
        event = _make_chat(user_id=42)
        await bus.emit("chat.message.sent", event)
        assert len(detector._messages) == 1
        assert detector._messages[0][1] == 42

    @pytest.mark.asyncio
    async def test_heat_callback_fires(self, bus, detector):
        moments = []

        @detector.on_heat
        async def cb(moment: HeatMoment):
            moments.append(moment)

        await detector.start()

        # Flood messages to trigger heat
        now = time.time()
        for i in range(50):
            detector._messages.append((now - 0.01 * i, i % 10))

        import asyncio
        await asyncio.sleep(0.2)  # Let the poll loop fire
        await detector.stop()

        assert len(moments) >= 1
        assert moments[0].score > 0

    @pytest.mark.asyncio
    async def test_start_stop(self, detector):
        await detector.start()
        assert detector._running is True
        await detector.stop()
        assert detector._running is False

    def test_window_pruning(self, detector):
        now = time.time()
        # Add old messages outside window
        for i in range(5):
            detector._messages.append((now - 20.0, i))
        # Add recent messages
        for i in range(5):
            detector._messages.append((now - 0.1, i + 10))

        score, mps, unique = detector.compute_score()
        # Old messages should be pruned
        assert len(detector._messages) == 5

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_fire(self, bus, detector):
        moments = []

        @detector.on_heat
        async def cb(moment):
            moments.append(moment)

        detector.config.cooldown_seconds = 100.0  # Very long cooldown
        await detector.start()

        now = time.time()
        for i in range(50):
            detector._messages.append((now, i))

        import asyncio
        await asyncio.sleep(0.2)
        # Flood again
        for i in range(50):
            detector._messages.append((time.time(), i + 50))
        await asyncio.sleep(0.2)
        await detector.stop()

        # Should only fire once due to cooldown
        assert len(moments) == 1
