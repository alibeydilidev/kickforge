"""
Auto-moderation engine.

Checks every chat message against configurable rules:
- Blacklisted words/phrases (regex)
- Excessive caps
- Spam (repeated messages)
- Blocked links

Actions: warn (chat message), timeout (API), ban (API).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from kickforge_core.events import ChatMessageEvent, Sender

logger = logging.getLogger("kickforge.bot.moderation")

# URL regex — catches common link patterns
_URL_PATTERN = re.compile(
    r"https?://\S+|www\.\S+|\S+\.\S+/\S+",
    re.IGNORECASE,
)


@dataclass
class ModerationAction:
    """Result of a moderation check."""

    action: str  # "warn", "timeout", "ban", "none"
    reason: str = ""
    duration: int = 0  # timeout seconds (only for "timeout")


@dataclass
class ModerationConfig:
    """Configuration for the auto-mod engine."""

    enabled: bool = True
    blocked_words: list[str] = field(default_factory=list)
    max_caps_percent: int = 70
    min_caps_length: int = 8  # Only check caps if message >= this length
    spam_max_identical: int = 3  # Max identical messages within spam window
    spam_window_seconds: float = 30.0
    links_allowed: bool = False
    link_whitelist: list[str] = field(default_factory=list)
    warn_message: str = "@{username}, please follow chat rules."
    timeout_duration: int = 600  # Default timeout in seconds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModerationConfig:
        """Create config from a YAML-loaded dict."""
        return cls(
            enabled=data.get("enabled", True),
            blocked_words=data.get("blocked_words", []),
            max_caps_percent=data.get("max_caps_percent", 70),
            min_caps_length=data.get("min_caps_length", 8),
            spam_max_identical=data.get("spam_max_identical", 3),
            spam_window_seconds=data.get("spam_window_seconds", 30.0),
            links_allowed=data.get("links_allowed", False),
            link_whitelist=data.get("link_whitelist", []),
            warn_message=data.get("warn_message", "@{username}, please follow chat rules."),
            timeout_duration=data.get("timeout_duration", 600),
        )


class ModerationEngine:
    """
    Checks messages against moderation rules.

    Usage:
        engine = ModerationEngine(config)
        action = engine.check(event)
        if action.action != "none":
            # take action
    """

    def __init__(self, config: ModerationConfig) -> None:
        self.config = config
        self._blocked_patterns: list[re.Pattern[str]] = []
        self._spam_history: dict[int, list[tuple[str, float]]] = {}
        self._compile_blocked_words()

    def _compile_blocked_words(self) -> None:
        """Compile blocked words/phrases into regex patterns."""
        self._blocked_patterns = []
        for word in self.config.blocked_words:
            try:
                self._blocked_patterns.append(re.compile(word, re.IGNORECASE))
            except re.error:
                # If it's not valid regex, escape it and compile as literal
                self._blocked_patterns.append(
                    re.compile(re.escape(word), re.IGNORECASE)
                )

    def check(self, event: ChatMessageEvent) -> ModerationAction:
        """
        Run all moderation checks on a message.
        Returns the most severe action needed.
        """
        if not self.config.enabled:
            return ModerationAction(action="none")

        sender = event.sender or Sender(user_id=0, username="unknown")

        # Skip moderation for mods and broadcaster
        badges = [b.lower() for b in sender.badges]
        if "broadcaster" in badges or "moderator" in badges:
            return ModerationAction(action="none")

        message = event.message

        # Check blacklist
        result = self._check_blacklist(message)
        if result:
            return result

        # Check caps
        result = self._check_caps(message)
        if result:
            return result

        # Check links
        result = self._check_links(message)
        if result:
            return result

        # Check spam
        result = self._check_spam(sender.user_id, message)
        if result:
            return result

        return ModerationAction(action="none")

    def _check_blacklist(self, message: str) -> Optional[ModerationAction]:
        """Check message against blocked words/phrases."""
        for pattern in self._blocked_patterns:
            if pattern.search(message):
                return ModerationAction(
                    action="timeout",
                    reason=f"Blocked word/phrase detected",
                    duration=self.config.timeout_duration,
                )
        return None

    def _check_caps(self, message: str) -> Optional[ModerationAction]:
        """Check for excessive caps."""
        if len(message) < self.config.min_caps_length:
            return None

        alpha_chars = [c for c in message if c.isalpha()]
        if not alpha_chars:
            return None

        caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) * 100
        if caps_ratio > self.config.max_caps_percent:
            return ModerationAction(
                action="warn",
                reason="Excessive caps",
            )
        return None

    def _check_links(self, message: str) -> Optional[ModerationAction]:
        """Check for unauthorized links."""
        if self.config.links_allowed:
            return None

        matches = _URL_PATTERN.findall(message)
        if not matches:
            return None

        # Check whitelist
        for url in matches:
            url_lower = url.lower()
            whitelisted = any(
                domain.lower() in url_lower for domain in self.config.link_whitelist
            )
            if not whitelisted:
                return ModerationAction(
                    action="timeout",
                    reason="Unauthorized link",
                    duration=self.config.timeout_duration,
                )
        return None

    def _check_spam(self, user_id: int, message: str) -> Optional[ModerationAction]:
        """Check for repeated messages (spam)."""
        now = time.time()
        cutoff = now - self.config.spam_window_seconds

        # Clean old entries
        if user_id in self._spam_history:
            self._spam_history[user_id] = [
                (msg, ts)
                for msg, ts in self._spam_history[user_id]
                if ts > cutoff
            ]
        else:
            self._spam_history[user_id] = []

        # Add current message
        self._spam_history[user_id].append((message.lower().strip(), now))

        # Count identical messages
        normalized = message.lower().strip()
        identical_count = sum(
            1 for msg, _ in self._spam_history[user_id] if msg == normalized
        )

        if identical_count > self.config.spam_max_identical:
            return ModerationAction(
                action="timeout",
                reason="Spam detected",
                duration=self.config.timeout_duration,
            )
        return None

    def update_config(self, config: ModerationConfig) -> None:
        """Update moderation config at runtime."""
        self.config = config
        self._compile_blocked_words()
