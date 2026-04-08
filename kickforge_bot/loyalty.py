"""
Loyalty / XP system backed by SQLite.

Tracks per-user XP, levels, watch time, messages, and provides
!rank, !top10, and !level commands.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("kickforge.bot.loyalty")

DEFAULT_LEVEL_THRESHOLDS: list[int] = [
    0, 100, 300, 600, 1000, 1500, 2200, 3000, 4000, 5500,
    7500, 10000, 13000, 17000, 22000, 28000, 35000, 43000, 52000, 65000,
]

XP_PER_MESSAGE = 5
XP_PER_WATCH_MINUTE = 1
XP_PER_SUB = 500


@dataclass
class UserStats:
    """Snapshot of a user's loyalty data."""

    user_id: int
    username: str
    xp: int = 0
    level: int = 0
    total_messages: int = 0
    total_watch_minutes: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


class LoyaltyDB:
    """
    SQLite-backed XP / loyalty system.

    Usage:
        db = LoyaltyDB("loyalty.db")
        db.add_xp(user_id=123, username="alice", amount=5)
        stats = db.get_stats(123)
        top = db.leaderboard(limit=10)
    """

    def __init__(
        self,
        db_path: str = "loyalty.db",
        level_thresholds: Optional[list[int]] = None,
    ) -> None:
        self.db_path = db_path
        self.level_thresholds = level_thresholds or DEFAULT_LEVEL_THRESHOLDS
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loyalty (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                total_messages INTEGER NOT NULL DEFAULT 0,
                total_watch_minutes INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            )
        """)
        conn.commit()

    def _calculate_level(self, xp: int) -> int:
        """Determine level from XP based on thresholds."""
        level = 0
        for i, threshold in enumerate(self.level_thresholds):
            if xp >= threshold:
                level = i
            else:
                break
        return level

    def _ensure_user(self, user_id: int, username: str) -> None:
        """Insert user if not exists."""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """
            INSERT OR IGNORE INTO loyalty
                (user_id, username, xp, level, total_messages, total_watch_minutes, first_seen, last_seen)
            VALUES (?, ?, 0, 0, 0, 0, ?, ?)
            """,
            (user_id, username, now, now),
        )
        # Always update username and last_seen
        conn.execute(
            "UPDATE loyalty SET username = ?, last_seen = ? WHERE user_id = ?",
            (username, now, user_id),
        )
        conn.commit()

    def add_xp(self, user_id: int, username: str, amount: int) -> UserStats:
        """Add XP to a user, recalculate level, return updated stats."""
        self._ensure_user(user_id, username)
        conn = self._get_conn()
        conn.execute(
            "UPDATE loyalty SET xp = xp + ?, last_seen = ? WHERE user_id = ?",
            (amount, time.time(), user_id),
        )
        # Recalculate level
        row = conn.execute("SELECT xp FROM loyalty WHERE user_id = ?", (user_id,)).fetchone()
        new_level = self._calculate_level(row["xp"])
        conn.execute(
            "UPDATE loyalty SET level = ? WHERE user_id = ?", (new_level, user_id)
        )
        conn.commit()
        return self.get_stats(user_id)

    def add_message(self, user_id: int, username: str) -> UserStats:
        """Record a chat message: +1 message count, +XP_PER_MESSAGE XP."""
        self._ensure_user(user_id, username)
        conn = self._get_conn()
        conn.execute(
            "UPDATE loyalty SET total_messages = total_messages + 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
        return self.add_xp(user_id, username, XP_PER_MESSAGE)

    def add_watch_minutes(self, user_id: int, username: str, minutes: int) -> None:
        """Add watch time minutes and corresponding XP."""
        self._ensure_user(user_id, username)
        conn = self._get_conn()
        conn.execute(
            "UPDATE loyalty SET total_watch_minutes = total_watch_minutes + ? WHERE user_id = ?",
            (minutes, user_id),
        )
        conn.commit()
        self.add_xp(user_id, username, minutes * XP_PER_WATCH_MINUTE)

    def get_stats(self, user_id: int) -> Optional[UserStats]:
        """Get a user's loyalty stats."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM loyalty WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        return UserStats(
            user_id=row["user_id"],
            username=row["username"],
            xp=row["xp"],
            level=row["level"],
            total_messages=row["total_messages"],
            total_watch_minutes=row["total_watch_minutes"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )

    def get_rank(self, user_id: int) -> int:
        """Get a user's rank (1-indexed) by XP. Returns 0 if not found."""
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT COUNT(*) + 1 as rank
            FROM loyalty
            WHERE xp > (SELECT COALESCE((SELECT xp FROM loyalty WHERE user_id = ?), -1))
            """,
            (user_id,),
        ).fetchone()
        # Check if user exists
        exists = conn.execute(
            "SELECT 1 FROM loyalty WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not exists:
            return 0
        return row["rank"]

    def leaderboard(self, limit: int = 10) -> list[UserStats]:
        """Get top users by XP."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM loyalty ORDER BY xp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            UserStats(
                user_id=r["user_id"],
                username=r["username"],
                xp=r["xp"],
                level=r["level"],
                total_messages=r["total_messages"],
                total_watch_minutes=r["total_watch_minutes"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
            )
            for r in rows
        ]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
