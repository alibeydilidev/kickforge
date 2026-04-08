"""
Batch clip exporter.

Ranks clips by heat score, exports top N, and optionally
sends a Discord webhook notification.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from kickforge_clip.detector import HeatMoment

logger = logging.getLogger("kickforge.clip.exporter")


@dataclass
class ExportedClip:
    """A clip that has been exported."""

    path: str
    rank: int
    score: float
    timestamp: float


class ClipExporter:
    """
    Sorts moments by score and exports the best clips.

    Usage:
        exporter = ClipExporter(output_dir="./export")
        exported = exporter.export(moments, clip_paths, top_n=5)
        await exporter.notify_discord(exported, webhook_url="https://...")
    """

    def __init__(self, output_dir: str = "./export") -> None:
        self.output_dir = output_dir

    def export(
        self,
        moments: list[HeatMoment],
        clip_paths: list[str],
        top_n: int = 5,
    ) -> list[ExportedClip]:
        """
        Rank clips by heat score and copy the top N to the export directory.

        Args:
            moments: Heat moments (same order as clip_paths).
            clip_paths: Corresponding clip file paths.
            top_n: Number of top clips to export.

        Returns:
            List of exported clips sorted by rank.
        """
        if len(moments) != len(clip_paths):
            raise ValueError("moments and clip_paths must have the same length")

        os.makedirs(self.output_dir, exist_ok=True)

        # Pair and sort by score descending
        paired = sorted(
            zip(moments, clip_paths),
            key=lambda x: x[0].score,
            reverse=True,
        )

        date_str = datetime.now().strftime("%Y%m%d")
        exported: list[ExportedClip] = []

        for rank, (moment, src_path) in enumerate(paired[:top_n], start=1):
            if not os.path.isfile(src_path):
                logger.warning("Clip not found, skipping: %s", src_path)
                continue

            ext = os.path.splitext(src_path)[1] or ".mp4"
            dest_name = f"{date_str}_{rank}_{moment.score:.0f}{ext}"
            dest_path = os.path.join(self.output_dir, dest_name)

            shutil.copy2(src_path, dest_path)
            exported.append(ExportedClip(
                path=dest_path,
                rank=rank,
                score=moment.score,
                timestamp=moment.timestamp,
            ))
            logger.info("Exported #%d: %s (score=%.1f)", rank, dest_name, moment.score)

        return exported

    @staticmethod
    def rank_moments(moments: list[HeatMoment]) -> list[HeatMoment]:
        """Sort moments by score descending."""
        return sorted(moments, key=lambda m: m.score, reverse=True)

    @staticmethod
    async def notify_discord(
        clips: list[ExportedClip],
        webhook_url: str,
    ) -> bool:
        """
        Send a Discord webhook notification with clip info.

        Returns True on success.
        """
        if not webhook_url or not clips:
            return False

        lines = [f"**KickForge Clip Export** — {len(clips)} clips"]
        for clip in clips:
            lines.append(f"#{clip.rank} — score {clip.score:.0f} — `{os.path.basename(clip.path)}`")

        payload = {
            "content": "\n".join(lines),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in (200, 204):
                    logger.info("Discord notification sent")
                    return True
                logger.warning("Discord webhook returned %d", resp.status_code)
                return False
        except Exception:
            logger.exception("Discord webhook failed")
            return False
