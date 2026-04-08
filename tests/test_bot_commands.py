"""Tests for kickforge_bot.commands.handler and builtin modules."""

import time

import pytest

from kickforge_core.events import ChatMessageEvent, Sender
from kickforge_bot.commands.handler import (
    CommandHandler,
    CommandContext,
    CommandDefinition,
    _get_user_permission_level,
    PERMISSION_LEVELS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    message: str,
    username: str = "testuser",
    user_id: int = 1,
    badges: list[str] | None = None,
    is_subscriber: bool = False,
    broadcaster_id: int = 99,
) -> ChatMessageEvent:
    return ChatMessageEvent(
        event_type="chat.message.sent",
        raw={},
        message_id="msg-1",
        message=message,
        broadcaster_user_id=broadcaster_id,
        sender=Sender(
            user_id=user_id,
            username=username,
            is_subscriber=is_subscriber,
            badges=badges or [],
        ),
    )


# ---------------------------------------------------------------------------
# CommandDefinition
# ---------------------------------------------------------------------------

class TestCommandDefinition:
    def test_no_cooldown(self):
        cd = CommandDefinition(name="test", handler=lambda ctx: None)
        assert cd.is_on_cooldown() == 0.0

    def test_cooldown_tracking(self):
        cd = CommandDefinition(name="test", handler=lambda ctx: None, cooldown=10.0)
        assert cd.is_on_cooldown() == 0.0
        cd.mark_used()
        assert cd.is_on_cooldown() > 0.0

    def test_cooldown_expired(self):
        cd = CommandDefinition(name="test", handler=lambda ctx: None, cooldown=0.1)
        cd._last_used["__global__"] = time.time() - 1.0
        assert cd.is_on_cooldown() == 0.0


# ---------------------------------------------------------------------------
# Permission levels
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_everyone(self):
        s = Sender(user_id=1, username="u")
        assert _get_user_permission_level(s) == PERMISSION_LEVELS["everyone"]

    def test_subscriber(self):
        s = Sender(user_id=1, username="u", is_subscriber=True)
        assert _get_user_permission_level(s) == PERMISSION_LEVELS["subscriber"]

    def test_moderator(self):
        s = Sender(user_id=1, username="u", badges=["moderator"])
        assert _get_user_permission_level(s) == PERMISSION_LEVELS["moderator"]

    def test_broadcaster(self):
        s = Sender(user_id=1, username="u", badges=["broadcaster"])
        assert _get_user_permission_level(s) == PERMISSION_LEVELS["broadcaster"]

    def test_subscriber_badge(self):
        s = Sender(user_id=1, username="u", badges=["subscriber"])
        assert _get_user_permission_level(s) == PERMISSION_LEVELS["subscriber"]


# ---------------------------------------------------------------------------
# CommandHandler
# ---------------------------------------------------------------------------

class TestCommandHandler:
    @pytest.fixture
    def handler(self):
        return CommandHandler(prefix="!")

    @pytest.mark.asyncio
    async def test_register_and_process(self, handler):
        replies = []

        @handler.command("ping")
        async def ping(ctx: CommandContext):
            replies.append("pong")
            await ctx.reply("pong")

        sent = []
        async def send_func(bid, content, reply_to):
            sent.append((bid, content, reply_to))

        event = _make_event("!ping")
        result = await handler.process(event, send_func)
        assert result is True
        assert replies == ["pong"]
        assert sent[0][1] == "pong"

    @pytest.mark.asyncio
    async def test_args_parsed(self, handler):
        captured_args = []

        @handler.command("say")
        async def say(ctx: CommandContext):
            captured_args.extend(ctx.args)

        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!say hello world")
        await handler.process(event, send_func)
        assert captured_args == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_unknown_command_ignored(self, handler):
        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!unknown")
        result = await handler.process(event, send_func)
        assert result is False

    @pytest.mark.asyncio
    async def test_non_command_ignored(self, handler):
        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("hello everyone")
        result = await handler.process(event, send_func)
        assert result is False

    @pytest.mark.asyncio
    async def test_permission_denied(self, handler):
        called = False

        @handler.command("modonly", permission="moderator")
        async def modonly(ctx: CommandContext):
            nonlocal called
            called = True

        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!modonly")  # No badges -> everyone
        result = await handler.process(event, send_func)
        assert result is False
        assert called is False

    @pytest.mark.asyncio
    async def test_permission_granted(self, handler):
        called = False

        @handler.command("modonly", permission="moderator")
        async def modonly(ctx: CommandContext):
            nonlocal called
            called = True

        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!modonly", badges=["moderator"])
        result = await handler.process(event, send_func)
        assert result is True
        assert called is True

    @pytest.mark.asyncio
    async def test_cooldown_blocks(self, handler):
        call_count = 0

        @handler.command("cd", cooldown=999.0)
        async def cd_cmd(ctx: CommandContext):
            nonlocal call_count
            call_count += 1

        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!cd")
        await handler.process(event, send_func)
        assert call_count == 1

        # Second call should be blocked by cooldown
        await handler.process(event, send_func)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_context_send_vs_reply(self, handler):
        sent = []

        @handler.command("test")
        async def test_cmd(ctx: CommandContext):
            await ctx.reply("reply-msg")
            await ctx.send("send-msg")

        async def send_func(bid, content, reply_to):
            sent.append((content, reply_to))

        event = _make_event("!test")
        await handler.process(event, send_func)
        assert sent[0] == ("reply-msg", "msg-1")  # reply has message_id
        assert sent[1] == ("send-msg", None)       # send has no reply_to

    def test_get_commands(self, handler):
        @handler.command("a")
        async def a(ctx):
            pass

        @handler.command("b")
        async def b(ctx):
            pass

        cmds = handler.get_commands()
        assert "a" in cmds
        assert "b" in cmds

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_crash(self, handler):
        @handler.command("boom")
        async def boom(ctx: CommandContext):
            raise ValueError("intentional error")

        async def send_func(bid, content, reply_to):
            pass

        event = _make_event("!boom")
        result = await handler.process(event, send_func)
        assert result is True  # Command was found, even though it raised
