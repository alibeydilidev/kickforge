"""Tests for kickforge_bot.timers module."""

import asyncio

import pytest

from kickforge_bot.timers import TimerManager, TimedMessage


class TestTimerManager:
    @pytest.mark.asyncio
    async def test_add_message(self):
        sent = []
        async def send(msg):
            sent.append(msg)

        mgr = TimerManager(send_func=send)
        mgr.add("hello", interval=0.1, only_when_live=False)
        assert mgr.message_count == 1

    @pytest.mark.asyncio
    async def test_timer_fires(self):
        sent = []
        async def send(msg):
            sent.append(msg)

        mgr = TimerManager(send_func=send)
        mgr.add("timer msg", interval=0.05, only_when_live=False)

        await mgr.start()
        await asyncio.sleep(0.15)
        await mgr.stop()

        assert len(sent) >= 1
        assert sent[0] == "timer msg"

    @pytest.mark.asyncio
    async def test_timer_stops(self):
        sent = []
        async def send(msg):
            sent.append(msg)

        mgr = TimerManager(send_func=send)
        mgr.add("msg", interval=0.05, only_when_live=False)

        await mgr.start()
        await asyncio.sleep(0.08)
        await mgr.stop()

        count_after_stop = len(sent)
        await asyncio.sleep(0.1)
        assert len(sent) == count_after_stop  # No new messages after stop

    @pytest.mark.asyncio
    async def test_live_check_skips_when_offline(self):
        sent = []
        async def send(msg):
            sent.append(msg)

        async def is_live():
            return False

        mgr = TimerManager(send_func=send, is_live_func=is_live)
        mgr.add("msg", interval=0.05, only_when_live=True)

        await mgr.start()
        await asyncio.sleep(0.15)
        await mgr.stop()

        assert len(sent) == 0  # Should not fire when offline

    @pytest.mark.asyncio
    async def test_live_check_fires_when_online(self):
        sent = []
        async def send(msg):
            sent.append(msg)

        async def is_live():
            return True

        mgr = TimerManager(send_func=send, is_live_func=is_live)
        mgr.add("online msg", interval=0.05, only_when_live=True)

        await mgr.start()
        await asyncio.sleep(0.15)
        await mgr.stop()

        assert len(sent) >= 1

    @pytest.mark.asyncio
    async def test_load_from_config(self):
        async def send(msg):
            pass

        mgr = TimerManager(send_func=send)
        mgr.load_from_config([
            {"message": "Follow!", "interval": 900},
            {"message": "Subscribe!", "interval": 600, "only_when_live": False},
        ])
        assert mgr.message_count == 2

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        async def send(msg):
            pass

        mgr = TimerManager(send_func=send)
        mgr.add("msg", interval=10, only_when_live=False)
        await mgr.start()
        await mgr.start()  # Should not create duplicate tasks
        assert len(mgr._tasks) == 1
        await mgr.stop()
