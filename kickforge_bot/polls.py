"""
Polls and giveaways for KickBot.

!poll create "Question?" "Option A" "Option B" [duration_seconds]
!poll vote <option_number>
!poll results
!giveaway start [keyword] [duration_seconds]
!giveaway draw
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("kickforge.bot.polls")


@dataclass
class Poll:
    """An active poll."""

    question: str
    options: list[str]
    votes: dict[int, int] = field(default_factory=dict)  # user_id -> option_index
    created_at: float = field(default_factory=time.time)
    duration: float = 0.0  # 0 = no auto-close
    closed: bool = False

    def vote(self, user_id: int, option_index: int) -> bool:
        """Cast a vote. Returns True if accepted, False if invalid."""
        if self.closed:
            return False
        if option_index < 0 or option_index >= len(self.options):
            return False
        self.votes[user_id] = option_index
        return True

    def results(self) -> list[tuple[str, int]]:
        """Return (option, vote_count) sorted by votes descending."""
        counts: dict[int, int] = {}
        for opt_idx in self.votes.values():
            counts[opt_idx] = counts.get(opt_idx, 0) + 1
        return [
            (self.options[i], counts.get(i, 0))
            for i in range(len(self.options))
        ]

    @property
    def total_votes(self) -> int:
        return len(self.votes)

    @property
    def is_expired(self) -> bool:
        if self.duration <= 0:
            return False
        return time.time() > self.created_at + self.duration


@dataclass
class Giveaway:
    """An active giveaway."""

    keyword: str
    entries: dict[int, str] = field(default_factory=dict)  # user_id -> username
    created_at: float = field(default_factory=time.time)
    duration: float = 0.0
    closed: bool = False
    winner_id: Optional[int] = None
    winner_name: Optional[str] = None

    def enter(self, user_id: int, username: str) -> bool:
        """Add a user entry. Returns True if new entry."""
        if self.closed:
            return False
        if user_id in self.entries:
            return False
        self.entries[user_id] = username
        return True

    def draw(self) -> Optional[tuple[int, str]]:
        """Pick a random winner. Returns (user_id, username) or None."""
        if not self.entries:
            return None
        self.closed = True
        uid = random.choice(list(self.entries.keys()))
        self.winner_id = uid
        self.winner_name = self.entries[uid]
        return uid, self.entries[uid]

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def is_expired(self) -> bool:
        if self.duration <= 0:
            return False
        return time.time() > self.created_at + self.duration


class PollManager:
    """Manages polls and giveaways."""

    def __init__(self) -> None:
        self._current_poll: Optional[Poll] = None
        self._current_giveaway: Optional[Giveaway] = None

    # -----------------------------------------------------------------------
    # Polls
    # -----------------------------------------------------------------------

    def create_poll(
        self,
        question: str,
        options: list[str],
        duration: float = 0.0,
    ) -> Poll:
        """Create a new poll, replacing any existing one."""
        self._current_poll = Poll(
            question=question,
            options=options,
            duration=duration,
        )
        logger.info("Poll created: %s (%d options)", question, len(options))
        return self._current_poll

    def vote(self, user_id: int, option_index: int) -> bool:
        """Cast a vote in the current poll."""
        if not self._current_poll:
            return False
        if self._current_poll.is_expired:
            self._current_poll.closed = True
            return False
        return self._current_poll.vote(user_id, option_index)

    def get_poll_results(self) -> Optional[list[tuple[str, int]]]:
        """Get current poll results."""
        if not self._current_poll:
            return None
        return self._current_poll.results()

    def close_poll(self) -> Optional[Poll]:
        """Close the current poll and return it."""
        if not self._current_poll:
            return None
        self._current_poll.closed = True
        poll = self._current_poll
        return poll

    @property
    def active_poll(self) -> Optional[Poll]:
        if self._current_poll and not self._current_poll.closed and not self._current_poll.is_expired:
            return self._current_poll
        return None

    # -----------------------------------------------------------------------
    # Giveaways
    # -----------------------------------------------------------------------

    def create_giveaway(
        self,
        keyword: str = "!enter",
        duration: float = 0.0,
    ) -> Giveaway:
        """Create a new giveaway."""
        self._current_giveaway = Giveaway(keyword=keyword, duration=duration)
        logger.info("Giveaway started (keyword: %s)", keyword)
        return self._current_giveaway

    def enter_giveaway(self, user_id: int, username: str) -> bool:
        """Enter the current giveaway."""
        if not self._current_giveaway:
            return False
        if self._current_giveaway.is_expired:
            self._current_giveaway.closed = True
            return False
        return self._current_giveaway.enter(user_id, username)

    def draw_giveaway(self) -> Optional[tuple[int, str]]:
        """Draw a winner for the current giveaway."""
        if not self._current_giveaway:
            return None
        return self._current_giveaway.draw()

    @property
    def active_giveaway(self) -> Optional[Giveaway]:
        if self._current_giveaway and not self._current_giveaway.closed and not self._current_giveaway.is_expired:
            return self._current_giveaway
        return None
