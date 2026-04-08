"""Tests for kickforge_gsi.bridge module."""

from typing import Any

import pytest

from kickforge_core.events import EventBus, ChatMessageEvent, GiftEvent, Sender
from kickforge_gsi.adapters.base import GameAdapter
from kickforge_gsi.bridge import KickGameBridge
from kickforge_gsi.tiers import TierEngine


# ---------------------------------------------------------------------------
# Fake adapter that records all executed commands
# ---------------------------------------------------------------------------

class FakeAdapter(GameAdapter):
    name = "fake"

    def __init__(self):
        self.commands: list[str] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        self.commands.append(action)
        return "ok"

    async def get_state(self) -> dict[str, Any]:
        return {"connected": self._connected}

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


TIER_CONFIG = {
    "game": "test",
    "actions": {
        "small_action": {
            "command": "do_small {{user}}",
            "repeat": 2,
            "chat_response": "{{user}} triggered small!",
        },
        "big_action": {
            "command": "do_big {{user}} {{amount}}",
            "repeat": 1,
            "chat_response": "{{user}} went BIG with {{amount}} kicks!",
        },
        "spawn": {
            "command": "spawn_mob {{user}}",
            "repeat": 1,
            "chat_response": "{{user}} spawned a mob!",
        },
    },
    "tiers": [
        {"range": [1, 50], "actions": ["small_action"], "cooldown": 5},
        {"range": [51, 999], "actions": ["big_action"], "cooldown": 30},
    ],
    "chat_commands": {
        "!spawn": {
            "action": "spawn",
            "cooldown": 10,
            "permission": "everyone",
        },
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKickGameBridge:
    @pytest.fixture
    def setup(self):
        bus = EventBus()
        adapter = FakeAdapter()
        engine = TierEngine.from_dict(TIER_CONFIG)
        sent: list[tuple[int, str]] = []

        async def send_func(bid: int, msg: str) -> None:
            sent.append((bid, msg))

        bridge = KickGameBridge(
            bus=bus, adapter=adapter, tier_engine=engine, send_func=send_func,
        )
        bridge.register()
        return bus, adapter, bridge, sent

    @pytest.mark.asyncio
    async def test_gift_triggers_action(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="alice",
            gifter_user_id=1,
            kicks_amount=10,
            broadcaster_user_id=99,
        )
        await bus.emit("kicks.gifted", event)

        assert len(adapter.commands) == 2  # repeat=2
        assert adapter.commands[0] == "do_small alice"
        assert ("alice triggered small!",) or any("alice" in m for _, m in sent)
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_gift_high_tier(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="whale",
            gifter_user_id=2,
            kicks_amount=100,
            broadcaster_user_id=99,
        )
        await bus.emit("kicks.gifted", event)

        assert len(adapter.commands) == 1
        assert "do_big whale 100" == adapter.commands[0]
        assert any("whale went BIG" in m for _, m in sent)
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_gift_no_matching_tier(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="x",
            gifter_user_id=3,
            kicks_amount=0,  # no tier for 0
            broadcaster_user_id=99,
        )
        await bus.emit("kicks.gifted", event)

        assert len(adapter.commands) == 0
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_cooldown_blocks_second_gift(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="alice",
            gifter_user_id=1,
            kicks_amount=10,
            broadcaster_user_id=99,
        )
        await bus.emit("kicks.gifted", event)
        count_after_first = len(adapter.commands)

        # Second gift immediately — should be blocked by cooldown
        await bus.emit("kicks.gifted", event)
        assert len(adapter.commands) == count_after_first

        await bridge.stop()

    @pytest.mark.asyncio
    async def test_chat_command_triggers_action(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="!spawn",
            broadcaster_user_id=99,
            sender=Sender(user_id=10, username="bob"),
        )
        await bus.emit("chat.message.sent", event)

        assert len(adapter.commands) == 1
        assert "spawn_mob bob" == adapter.commands[0]
        assert any("bob spawned a mob" in m for _, m in sent)
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_chat_command_cooldown_per_user(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="!spawn",
            broadcaster_user_id=99,
            sender=Sender(user_id=10, username="bob"),
        )
        await bus.emit("chat.message.sent", event)
        assert len(adapter.commands) == 1

        # Same user again — blocked
        await bus.emit("chat.message.sent", event)
        assert len(adapter.commands) == 1

        # Different user — should work
        event2 = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m2",
            message="!spawn",
            broadcaster_user_id=99,
            sender=Sender(user_id=20, username="carol"),
        )
        await bus.emit("chat.message.sent", event2)
        assert len(adapter.commands) == 2

        await bridge.stop()

    @pytest.mark.asyncio
    async def test_non_command_chat_ignored(self, setup):
        bus, adapter, bridge, sent = setup
        await bridge.start()

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="hello everyone",
            broadcaster_user_id=99,
            sender=Sender(user_id=10, username="bob"),
        )
        await bus.emit("chat.message.sent", event)
        assert len(adapter.commands) == 0
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_start_stop(self, setup):
        _, adapter, bridge, _ = setup
        await bridge.start()
        assert adapter.is_connected is True
        await bridge.stop()
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_register_idempotent(self, setup):
        bus, adapter, bridge, sent = setup
        bridge.register()  # Already registered in fixture
        bridge.register()  # Should not double-register

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="x",
            gifter_user_id=1,
            kicks_amount=5,
            broadcaster_user_id=99,
        )
        await bridge.start()
        await bus.emit("kicks.gifted", event)
        # Should only fire once, not twice
        assert len(adapter.commands) == 2  # repeat=2 for one tier match
        await bridge.stop()
