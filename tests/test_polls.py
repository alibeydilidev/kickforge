"""Tests for kickforge_bot.polls module."""

import time

import pytest

from kickforge_bot.polls import Poll, Giveaway, PollManager


class TestPoll:
    def test_vote(self):
        poll = Poll(question="Best color?", options=["Red", "Blue", "Green"])
        assert poll.vote(user_id=1, option_index=0) is True
        assert poll.vote(user_id=2, option_index=1) is True
        assert poll.total_votes == 2

    def test_vote_changes(self):
        poll = Poll(question="Q?", options=["A", "B"])
        poll.vote(1, 0)
        poll.vote(1, 1)  # Change vote
        assert poll.total_votes == 1
        results = poll.results()
        assert results[0][1] == 0  # Option A: 0 votes
        assert results[1][1] == 1  # Option B: 1 vote

    def test_vote_invalid_index(self):
        poll = Poll(question="Q?", options=["A", "B"])
        assert poll.vote(1, 5) is False
        assert poll.vote(1, -1) is False

    def test_vote_on_closed_poll(self):
        poll = Poll(question="Q?", options=["A", "B"], closed=True)
        assert poll.vote(1, 0) is False

    def test_results(self):
        poll = Poll(question="Q?", options=["A", "B", "C"])
        poll.vote(1, 0)
        poll.vote(2, 0)
        poll.vote(3, 2)
        results = poll.results()
        assert results[0] == ("A", 2)
        assert results[1] == ("B", 0)
        assert results[2] == ("C", 1)

    def test_expiry(self):
        poll = Poll(
            question="Q?",
            options=["A"],
            duration=0.01,
            created_at=time.time() - 1.0,
        )
        assert poll.is_expired is True

    def test_no_expiry(self):
        poll = Poll(question="Q?", options=["A"], duration=0.0)
        assert poll.is_expired is False


class TestGiveaway:
    def test_enter(self):
        g = Giveaway(keyword="!enter")
        assert g.enter(1, "alice") is True
        assert g.enter(2, "bob") is True
        assert g.entry_count == 2

    def test_no_duplicate_entry(self):
        g = Giveaway(keyword="!enter")
        g.enter(1, "alice")
        assert g.enter(1, "alice") is False
        assert g.entry_count == 1

    def test_draw(self):
        g = Giveaway(keyword="!enter")
        g.enter(1, "alice")
        g.enter(2, "bob")
        winner = g.draw()
        assert winner is not None
        uid, name = winner
        assert uid in (1, 2)
        assert g.closed is True

    def test_draw_empty(self):
        g = Giveaway(keyword="!enter")
        assert g.draw() is None

    def test_enter_closed(self):
        g = Giveaway(keyword="!enter", closed=True)
        assert g.enter(1, "alice") is False

    def test_expiry(self):
        g = Giveaway(keyword="!enter", duration=0.01, created_at=time.time() - 1.0)
        assert g.is_expired is True


class TestPollManager:
    def test_create_and_vote(self):
        mgr = PollManager()
        poll = mgr.create_poll("Best?", ["A", "B"])
        assert poll.question == "Best?"
        assert mgr.vote(1, 0) is True
        results = mgr.get_poll_results()
        assert results is not None
        assert results[0] == ("A", 1)

    def test_close_poll(self):
        mgr = PollManager()
        mgr.create_poll("Q?", ["A", "B"])
        mgr.vote(1, 0)
        closed = mgr.close_poll()
        assert closed is not None
        assert closed.closed is True
        # Active poll should be None now
        assert mgr.active_poll is None

    def test_no_poll(self):
        mgr = PollManager()
        assert mgr.vote(1, 0) is False
        assert mgr.get_poll_results() is None
        assert mgr.close_poll() is None

    def test_create_giveaway(self):
        mgr = PollManager()
        g = mgr.create_giveaway(keyword="!win")
        assert g.keyword == "!win"

    def test_giveaway_flow(self):
        mgr = PollManager()
        mgr.create_giveaway("!enter")
        assert mgr.enter_giveaway(1, "alice") is True
        assert mgr.enter_giveaway(2, "bob") is True
        winner = mgr.draw_giveaway()
        assert winner is not None
        assert mgr.active_giveaway is None  # Closed after draw

    def test_no_giveaway(self):
        mgr = PollManager()
        assert mgr.enter_giveaway(1, "a") is False
        assert mgr.draw_giveaway() is None

    def test_active_poll_expired(self):
        mgr = PollManager()
        mgr.create_poll("Q?", ["A"], duration=0.01)
        mgr._current_poll.created_at = time.time() - 1.0
        assert mgr.active_poll is None
