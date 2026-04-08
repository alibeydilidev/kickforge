"""Tests for kickforge_bot.moderation module."""

import pytest

from kickforge_core.events import ChatMessageEvent, Sender
from kickforge_bot.moderation import ModerationConfig, ModerationEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    message: str,
    username: str = "user1",
    user_id: int = 1,
    badges: list[str] | None = None,
    is_subscriber: bool = False,
) -> ChatMessageEvent:
    return ChatMessageEvent(
        event_type="chat.message.sent",
        raw={},
        message_id="m1",
        message=message,
        broadcaster_user_id=99,
        sender=Sender(
            user_id=user_id,
            username=username,
            is_subscriber=is_subscriber,
            badges=badges or [],
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestModerationEngine:
    @pytest.fixture
    def engine(self):
        config = ModerationConfig(
            blocked_words=["badword", r"b[a@]d\s*phrase"],
            max_caps_percent=70,
            min_caps_length=8,
            spam_max_identical=2,
            spam_window_seconds=30.0,
            links_allowed=False,
            link_whitelist=["kick.com", "youtube.com"],
            timeout_duration=300,
        )
        return ModerationEngine(config)

    def test_clean_message(self, engine):
        event = _make_event("Hello everyone!")
        action = engine.check(event)
        assert action.action == "none"

    def test_blacklist_exact(self, engine):
        event = _make_event("this has a badword in it")
        action = engine.check(event)
        assert action.action == "timeout"
        assert "Blocked" in action.reason

    def test_blacklist_regex(self, engine):
        event = _make_event("this is a b@d phrase right here")
        action = engine.check(event)
        assert action.action == "timeout"

    def test_caps_warning(self, engine):
        event = _make_event("THIS IS ALL CAPS MESSAGE")
        action = engine.check(event)
        assert action.action == "warn"
        assert "caps" in action.reason.lower()

    def test_caps_short_message_ignored(self, engine):
        event = _make_event("HI")
        action = engine.check(event)
        assert action.action == "none"

    def test_caps_below_threshold(self, engine):
        event = _make_event("Hello World This is Fine!")
        action = engine.check(event)
        assert action.action == "none"

    def test_link_blocked(self, engine):
        event = _make_event("check out https://evil.com/malware")
        action = engine.check(event)
        assert action.action == "timeout"
        assert "link" in action.reason.lower()

    def test_link_whitelisted(self, engine):
        event = _make_event("check out https://kick.com/streamer")
        action = engine.check(event)
        assert action.action == "none"

    def test_links_allowed_mode(self):
        config = ModerationConfig(links_allowed=True)
        engine = ModerationEngine(config)
        event = _make_event("https://anything.com")
        action = engine.check(event)
        assert action.action == "none"

    def test_spam_detection(self, engine):
        event = _make_event("spam spam spam", user_id=42)
        engine.check(event)  # 1st
        engine.check(event)  # 2nd
        action = engine.check(event)  # 3rd -> over limit of 2
        assert action.action == "timeout"
        assert "spam" in action.reason.lower()

    def test_spam_different_users(self, engine):
        e1 = _make_event("same message", user_id=1)
        e2 = _make_event("same message", user_id=2)
        engine.check(e1)
        engine.check(e1)
        action = engine.check(e2)
        # Different user, should not be flagged
        assert action.action == "none"

    def test_moderator_bypasses(self, engine):
        event = _make_event("badword", badges=["moderator"])
        action = engine.check(event)
        assert action.action == "none"

    def test_broadcaster_bypasses(self, engine):
        event = _make_event("THIS IS ALL CAPS FROM BROADCASTER", badges=["broadcaster"])
        action = engine.check(event)
        assert action.action == "none"

    def test_disabled_engine(self):
        config = ModerationConfig(enabled=False, blocked_words=["bad"])
        engine = ModerationEngine(config)
        event = _make_event("bad")
        action = engine.check(event)
        assert action.action == "none"

    def test_config_from_dict(self):
        cfg = ModerationConfig.from_dict({
            "blocked_words": ["test"],
            "max_caps_percent": 80,
            "links_allowed": True,
        })
        assert cfg.blocked_words == ["test"]
        assert cfg.max_caps_percent == 80
        assert cfg.links_allowed is True

    def test_update_config(self, engine):
        new_config = ModerationConfig(blocked_words=["newbadword"])
        engine.update_config(new_config)
        event = _make_event("newbadword")
        action = engine.check(event)
        assert action.action == "timeout"
