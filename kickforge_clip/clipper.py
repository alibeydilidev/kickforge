"""
FFmpeg-based clip extraction.

Cuts clips from a video file around heat-moment timestamps.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("kickforge.clip.clipper")


@dataclass
class ClipResult:
    """Result of a clip extraction."""

    output_path: str
    start_time: float
    duration: float
    success: bool
    error: str = ""


def check_ffmpeg() -> bool:
    """Check if FFmpeg is installed and accessible."""
    return shutil.which("ffmpeg") is not None


class Clipper:
    """
    Extracts clips from video files using FFmpeg.

    Usage:
        clipper = Clipper(input_path="stream.mp4", output_dir="./clips")
        result = clipper.cut(timestamp=3600.0)  # cut around 1h mark
    """

    def __init__(
        self,
        input_path: str,
        output_dir: str = "./clips",
        clip_before: float = 30.0,
        clip_after: float = 30.0,
    ) -> None:
        self.input_path = input_path
        self.output_dir = output_dir
        self.clip_before = clip_before
        self.clip_after = clip_after
        self._clip_count = 0

    def cut(
        self,
        timestamp: float,
        output_name: Optional[str] = None,
    ) -> ClipResult:
        """
        Cut a clip around a timestamp.

        Args:
            timestamp: Center point in seconds from the start.
            output_name: Optional output filename (auto-generated if None).

        Returns:
            ClipResult with the output path and status.
        """
        if not check_ffmpeg():
            return ClipResult(
                output_path="",
                start_time=0,
                duration=0,
                success=False,
                error="FFmpeg not found. Install FFmpeg to use the clip pipeline.",
            )

        if not os.path.isfile(self.input_path):
            return ClipResult(
                output_path="",
                start_time=0,
                duration=0,
                success=False,
                error=f"Input file not found: {self.input_path}",
            )

        os.makedirs(self.output_dir, exist_ok=True)

        start = max(0.0, timestamp - self.clip_before)
        duration = self.clip_before + self.clip_after

        self._clip_count += 1
        if output_name is None:
            ext = Path(self.input_path).suffix or ".mp4"
            output_name = f"clip_{self._clip_count:04d}{ext}"

        output_path = os.path.join(self.output_dir, output_name)

        cmd = build_ffmpeg_cut_cmd(
            input_path=self.input_path,
            output_path=output_path,
            start=start,
            duration=duration,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return ClipResult(
                    output_path=output_path,
                    start_time=start,
                    duration=duration,
                    success=False,
                    error=result.stderr[:500],
                )
            logger.info("Clip extracted: %s (%.1fs from %.1f)", output_path, duration, start)
            return ClipResult(
                output_path=output_path,
                start_time=start,
                duration=duration,
                success=True,
            )
        except subprocess.TimeoutExpired:
            return ClipResult(
                output_path=output_path,
                start_time=start,
                duration=duration,
                success=False,
                error="FFmpeg timed out",
            )
        except Exception as exc:
            return ClipResult(
                output_path=output_path,
                start_time=start,
                duration=duration,
                success=False,
                error=str(exc),
            )


def build_ffmpeg_cut_cmd(
    input_path: str,
    output_path: str,
    start: float,
    duration: float,
) -> list[str]:
    """Build the FFmpeg command for cutting a clip."""
    return [
        "ffmpeg",
        "-y",
        "-ss", f"{start:.2f}",
        "-t", f"{duration:.2f}",
        "-i", input_path,
        "-c", "copy",
        output_path,
    ]
