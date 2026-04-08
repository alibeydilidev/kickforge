"""Integration tests for KickBot."""

import os
import tempfile
import time

import httpx
import pytest

from kickforge_core.auth import TokenPair
from kickforge_core.events import ChatMessageEvent, GiftEvent, SubscriptionEvent, Sender
from kickforge_bot.bot import KickBot
from kickforge_bot.plugins.base import Plugin


def _make_bot(db_path: str | None = None) -> KickBot:
    """Create a KickBot with mocked HTTP for testing."""
    bot = KickBot(
        client_id="test",
        client_secret="secret",
        verify_signatures=False,
        log_level="WARNING",
        db_path=db_path or ":memory:",
    )
    # Mock token so API calls don't fail
    bot.auth._tokens["app"] = TokenPair(
        access_token="mock", expires_at=time.time() + 3600
    )
    bot.auth._tokens["user"] = TokenPair(
        access_token="mock-user", expires_at=time.time() + 3600
    )
    return bot


def _mock_api(bot: KickBot) -> list[tuple[str, str]]:
    """Replace bot API HTTP with mock, return list of sent messages."""
    sent: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json
        if "/api/v1/chat" in str(request.url) and request.method == "POST":
            data = json.loads(request.content)
            sent.append((str(data.get("broadcaster_user_id")), data.get("content", "")))
        return httpx.Response(200, json={"data": {}})

    bot.api._http = httpx.AsyncClient(
        base_url="https://api.kick.com",
        transport=httpx.MockTransport(handler),
    )
    return sent


class TestKickBotIntegration:
    @pytest.mark.asyncio
    async def test_custom_command(self):
        bot = _make_bot()
        sent = _mock_api(bot)

        @bot.command("!hello")
        async def hello(ctx):
            await ctx.reply(f"Hi {ctx.sender.username}!")

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="!hello",
            broadcaster_user_id=99,
            sender=Sender(user_id=1, username="alice"),
        )
        await bot.bus.emit("chat.message.sent", event)

        assert any("Hi alice!" in msg for _, msg in sent)
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_loyalty_xp_on_message(self):
        bot = _make_bot()
        _mock_api(bot)

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="just chatting",
            broadcaster_user_id=99,
            sender=Sender(user_id=42, username="bob"),
        )
        await bot.bus.emit("chat.message.sent", event)

        stats = bot.loyalty.get_stats(42)
        assert stats is not None
        assert stats.xp == 5  # XP_PER_MESSAGE
        assert stats.total_messages == 1
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_loyalty_xp_on_gift(self):
        bot = _make_bot()
        _mock_api(bot)

        event = GiftEvent(
            event_type="kicks.gifted",
            raw={},
            gifter_username="generous",
            gifter_user_id=10,
            kicks_amount=200,
            broadcaster_user_id=99,
        )
        await bot.bus.emit("kicks.gifted", event)

        stats = bot.loyalty.get_stats(10)
        assert stats is not None
        assert stats.xp == 200
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_loyalty_xp_on_sub(self):
        bot = _make_bot()
        _mock_api(bot)

        event = SubscriptionEvent(
            event_type="channel.subscription.new",
            raw={},
            subscriber_username="newsub",
            subscriber_user_id=20,
            broadcaster_user_id=99,
        )
        await bot.bus.emit("channel.subscription.new", event)

        stats = bot.loyalty.get_stats(20)
        assert stats is not None
        assert stats.xp == 500  # XP_PER_SUB
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_moderation_blocks_message(self):
        from kickforge_bot.moderation import ModerationConfig
        bot = _make_bot()
        bot.moderation.update_config(ModerationConfig(blocked_words=["badword"]))
        sent = _mock_api(bot)

        # Register a command that should NOT fire
        cmd_called = False

        @bot.command("!test")
        async def test_cmd(ctx):
            nonlocal cmd_called
            cmd_called = True

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="badword !test",
            broadcaster_user_id=99,
            sender=Sender(user_id=1, username="troll"),
        )
        await bot.bus.emit("chat.message.sent", event)

        assert cmd_called is False  # Command should not fire on moderated message
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_plugin_receives_events(self):
        bot = _make_bot()
        _mock_api(bot)

        class TestPlugin(Plugin):
            name = "test"
            def __init__(self):
                self.messages = []
            async def on_message(self, event):
                self.messages.append(event.message)

        plugin = TestPlugin()
        await bot.load_plugin(plugin)
        assert plugin in bot._plugins

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="hi from plugin test",
            broadcaster_user_id=99,
            sender=Sender(user_id=1, username="user"),
        )
        await bot.bus.emit("chat.message.sent", event)

        assert "hi from plugin test" in plugin.messages
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_giveaway_keyword_entry(self):
        bot = _make_bot()
        _mock_api(bot)

        bot.polls.create_giveaway(keyword="!enter")

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="!enter",
            broadcaster_user_id=99,
            sender=Sender(user_id=50, username="fan"),
        )
        await bot.bus.emit("chat.message.sent", event)

        g = bot.polls.active_giveaway
        assert g is not None
        assert g.entry_count == 1
        assert 50 in g.entries
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_builtin_help_command(self):
        bot = _make_bot()
        sent = _mock_api(bot)

        event = ChatMessageEvent(
            event_type="chat.message.sent",
            raw={},
            message_id="m1",
            message="!help",
            broadcaster_user_id=99,
            sender=Sender(user_id=1, username="user"),
        )
        await bot.bus.emit("chat.message.sent", event)

        assert any("help" in msg.lower() for _, msg in sent)
        await bot.api.close()

    @pytest.mark.asyncio
    async def test_load_config(self):
        bot = _make_bot()
        config = {
            "bot": {
                "moderation": {
                    "blocked_words": ["configbad"],
                    "max_caps_percent": 90,
                },
                "timed_messages": [
                    {"message": "Follow!", "interval": 900},
                ],
            }
        }
        bot.load_config(config)
        assert "configbad" in [
            p.pattern for p in bot.moderation._blocked_patterns
        ]
        assert bot.timers.message_count == 1
