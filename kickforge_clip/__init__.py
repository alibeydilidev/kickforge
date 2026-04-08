"""
KickForge Clip — auto-detect hype moments, cut clips, export to Shorts.
"""

from kickforge_clip.detector import HeatDetector, HeatMoment, HeatConfig
from kickforge_clip.clipper import Clipper, ClipResult, check_ffmpeg, build_ffmpeg_cut_cmd
from kickforge_clip.formatter import format_vertical, build_vertical_cmd, FormatResult
from kickforge_clip.exporter import ClipExporter, ExportedClip

__all__ = [
    "HeatDetector",
    "HeatMoment",
    "HeatConfig",
    "Clipper",
    "ClipResult",
    "check_ffmpeg",
    "build_ffmpeg_cut_cmd",
    "format_vertical",
    "build_vertical_cmd",
    "FormatResult",
    "ClipExporter",
    "ExportedClip",
]
