"""Tests for kickforge_bot.loyalty module."""

import os
import tempfile

import pytest

from kickforge_bot.loyalty import LoyaltyDB, UserStats, XP_PER_MESSAGE


class TestLoyaltyDB:
    @pytest.fixture
    def db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        database = LoyaltyDB(db_path=path)
        yield database
        database.close()
        os.unlink(path)

    def test_add_xp(self, db):
        stats = db.add_xp(user_id=1, username="alice", amount=100)
        assert stats.xp == 100
        assert stats.username == "alice"

    def test_add_xp_accumulates(self, db):
        db.add_xp(1, "alice", 50)
        stats = db.add_xp(1, "alice", 30)
        assert stats.xp == 80

    def test_add_message(self, db):
        stats = db.add_message(1, "alice")
        assert stats.xp == XP_PER_MESSAGE
        assert stats.total_messages == 1

        stats = db.add_message(1, "alice")
        assert stats.xp == XP_PER_MESSAGE * 2
        assert stats.total_messages == 2

    def test_get_stats_nonexistent(self, db):
        assert db.get_stats(9999) is None

    def test_get_stats(self, db):
        db.add_xp(1, "alice", 200)
        stats = db.get_stats(1)
        assert stats is not None
        assert stats.xp == 200
        assert stats.user_id == 1

    def test_level_calculation(self, db):
        # Level thresholds: 0, 100, 300, ...
        stats = db.add_xp(1, "alice", 50)
        assert stats.level == 0

        stats = db.add_xp(1, "alice", 60)  # total 110
        assert stats.level == 1

        stats = db.add_xp(1, "alice", 200)  # total 310
        assert stats.level == 2

    def test_leaderboard(self, db):
        db.add_xp(1, "alice", 500)
        db.add_xp(2, "bob", 200)
        db.add_xp(3, "charlie", 800)

        top = db.leaderboard(limit=10)
        assert len(top) == 3
        assert top[0].username == "charlie"
        assert top[1].username == "alice"
        assert top[2].username == "bob"

    def test_leaderboard_limit(self, db):
        for i in range(20):
            db.add_xp(i + 1, f"user{i}", (i + 1) * 10)

        top = db.leaderboard(limit=5)
        assert len(top) == 5

    def test_get_rank(self, db):
        db.add_xp(1, "alice", 500)
        db.add_xp(2, "bob", 200)
        db.add_xp(3, "charlie", 800)

        assert db.get_rank(3) == 1  # charlie first
        assert db.get_rank(1) == 2  # alice second
        assert db.get_rank(2) == 3  # bob third

    def test_get_rank_nonexistent(self, db):
        assert db.get_rank(9999) == 0

    def test_add_watch_minutes(self, db):
        db.add_watch_minutes(1, "alice", 10)
        stats = db.get_stats(1)
        assert stats is not None
        assert stats.total_watch_minutes == 10
        assert stats.xp == 10  # 1 XP per minute

    def test_username_updated(self, db):
        db.add_xp(1, "old_name", 10)
        db.add_xp(1, "new_name", 10)
        stats = db.get_stats(1)
        assert stats is not None
        assert stats.username == "new_name"

    def test_custom_level_thresholds(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = LoyaltyDB(db_path=path, level_thresholds=[0, 50, 150])
        try:
            stats = db.add_xp(1, "alice", 60)
            assert stats.level == 1
            stats = db.add_xp(1, "alice", 100)  # total 160
            assert stats.level == 2
        finally:
            db.close()
            os.unlink(path)
