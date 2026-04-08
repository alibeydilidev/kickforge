"""Tests for kickforge_gsi.cooldown module."""

import asyncio
import time

import pytest

from kickforge_gsi.cooldown import CooldownManager


class TestCooldownManager:
    @pytest.mark.asyncio
    async def test_no_cooldown(self):
        cd = CooldownManager()
        assert await cd.check("action") == 0.0

    @pytest.mark.asyncio
    async def test_global_cooldown(self):
        cd = CooldownManager()
        await cd.trigger("boom", cooldown=10.0)
        remaining = await cd.check("boom")
        assert remaining > 9.0

    @pytest.mark.asyncio
    async def test_cooldown_expires(self):
        cd = CooldownManager()
        await cd.trigger("fast", cooldown=0.05)
        await asyncio.sleep(0.1)
        assert await cd.check("fast") == 0.0

    @pytest.mark.asyncio
    async def test_per_user_cooldown(self):
        cd = CooldownManager()
        await cd.trigger("spell", cooldown=10.0, user_id=42)
        # User 42 on cooldown
        assert await cd.check("spell", user_id=42) > 0
        # User 99 not on cooldown
        assert await cd.check("spell", user_id=99) == 0.0

    @pytest.mark.asyncio
    async def test_global_blocks_all_users(self):
        cd = CooldownManager()
        await cd.trigger("nuke", cooldown=10.0)  # global
        # Even per-user check should hit the global cooldown first
        assert await cd.check("nuke", user_id=1) > 0

    @pytest.mark.asyncio
    async def test_reset_global(self):
        cd = CooldownManager()
        await cd.trigger("action", cooldown=100.0)
        assert await cd.check("action") > 0
        await cd.reset("action")
        assert await cd.check("action") == 0.0

    @pytest.mark.asyncio
    async def test_reset_user(self):
        cd = CooldownManager()
        await cd.trigger("spell", cooldown=100.0, user_id=5)
        assert await cd.check("spell", user_id=5) > 0
        await cd.reset("spell", user_id=5)
        assert await cd.check("spell", user_id=5) == 0.0

    @pytest.mark.asyncio
    async def test_reset_all(self):
        cd = CooldownManager()
        await cd.trigger("a", cooldown=100.0)
        await cd.trigger("b", cooldown=100.0, user_id=1)
        await cd.reset_all()
        assert await cd.check("a") == 0.0
        assert await cd.check("b", user_id=1) == 0.0

    @pytest.mark.asyncio
    async def test_independent_actions(self):
        cd = CooldownManager()
        await cd.trigger("action_a", cooldown=10.0)
        assert await cd.check("action_b") == 0.0
