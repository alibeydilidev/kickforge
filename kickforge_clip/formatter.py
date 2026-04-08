"""
Shorts formatter — converts 16:9 clips to 9:16 for mobile platforms.

Uses FFmpeg filter chains: crop -> scale.
Optional subtitle overlay via Whisper (if installed).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("kickforge.clip.formatter")


@dataclass
class FormatResult:
    """Result of a format operation."""

    output_path: str
    success: bool
    error: str = ""


def format_vertical(
    input_path: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> FormatResult:
    """
    Convert a 16:9 clip to 9:16 (center crop + scale).

    Args:
        input_path: Source clip.
        output_path: Destination path.
        width: Output width (default 1080).
        height: Output height (default 1920).
    """
    if not shutil.which("ffmpeg"):
        return FormatResult(output_path="", success=False, error="FFmpeg not found")

    if not os.path.isfile(input_path):
        return FormatResult(output_path="", success=False, error=f"File not found: {input_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = build_vertical_cmd(input_path, output_path, width, height)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return FormatResult(output_path=output_path, success=False, error=result.stderr[:500])
        logger.info("Formatted vertical: %s", output_path)
        return FormatResult(output_path=output_path, success=True)
    except subprocess.TimeoutExpired:
        return FormatResult(output_path=output_path, success=False, error="FFmpeg timed out")
    except Exception as exc:
        return FormatResult(output_path=output_path, success=False, error=str(exc))


def build_vertical_cmd(
    input_path: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> list[str]:
    """Build FFmpeg command for 16:9 → 9:16 center crop + scale."""
    # Center crop to 9:16 aspect from source, then scale to target
    filter_chain = (
        f"crop=ih*9/16:ih,scale={width}:{height}"
    )
    return [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", filter_chain,
        "-c:a", "copy",
        output_path,
    ]


def add_subtitles(
    input_path: str,
    output_path: str,
    srt_path: Optional[str] = None,
) -> FormatResult:
    """
    Overlay subtitles on a video.

    If ``srt_path`` is not provided, attempts to generate subtitles
    using Whisper (must be installed separately).
    """
    if srt_path and os.path.isfile(srt_path):
        return _burn_srt(input_path, output_path, srt_path)

    # Try Whisper auto-transcription
    try:
        import whisper  # type: ignore[import-untyped]
    except ImportError:
        return FormatResult(
            output_path="",
            success=False,
            error="Whisper not installed. Install with: pip install openai-whisper",
        )

    try:
        model = whisper.load_model("base")
        result = model.transcribe(input_path)
        # Write SRT
        srt_path = input_path + ".srt"
        _write_srt(result["segments"], srt_path)
        return _burn_srt(input_path, output_path, srt_path)
    except Exception as exc:
        return FormatResult(output_path="", success=False, error=f"Whisper failed: {exc}")


def _burn_srt(input_path: str, output_path: str, srt_path: str) -> FormatResult:
    """Burn SRT subtitles into video."""
    if not shutil.which("ffmpeg"):
        return FormatResult(output_path="", success=False, error="FFmpeg not found")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"subtitles={srt_path}:force_style='FontSize=24,PrimaryColour=&HFFFFFF&'",
        "-c:a", "copy",
        output_path,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            return FormatResult(output_path=output_path, success=False, error=res.stderr[:500])
        return FormatResult(output_path=output_path, success=True)
    except Exception as exc:
        return FormatResult(output_path="", success=False, error=str(exc))


def _write_srt(segments: list[dict], path: str) -> None:
    """Write Whisper segments as SRT."""
    with open(path, "w") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_srt_time(seg["start"])
            end = _format_srt_time(seg["end"])
            text = seg["text"].strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
