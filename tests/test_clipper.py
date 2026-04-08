"""Tests for kickforge_clip.clipper module."""

import pytest

from kickforge_clip.clipper import Clipper, ClipResult, build_ffmpeg_cut_cmd


class TestBuildFFmpegCmd:
    def test_basic_cmd(self):
        cmd = build_ffmpeg_cut_cmd(
            input_path="stream.mp4",
            output_path="clip.mp4",
            start=100.0,
            duration=60.0,
        )
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "-ss" in cmd
        idx = cmd.index("-ss")
        assert cmd[idx + 1] == "100.00"
        assert "-t" in cmd
        idx = cmd.index("-t")
        assert cmd[idx + 1] == "60.00"
        assert "-i" in cmd
        assert "stream.mp4" in cmd
        assert "-c" in cmd
        assert "copy" in cmd
        assert cmd[-1] == "clip.mp4"

    def test_start_clamped(self):
        """If timestamp is small, start should be 0."""
        clipper = Clipper(input_path="test.mp4", output_dir="/tmp/clips")
        # With timestamp=10, clip_before=30, start should be 0
        start = max(0.0, 10.0 - clipper.clip_before)
        assert start == 0.0

    def test_clip_counter(self):
        clipper = Clipper(input_path="test.mp4")
        assert clipper._clip_count == 0

    def test_cut_missing_file(self):
        clipper = Clipper(input_path="/nonexistent/file.mp4", output_dir="/tmp/test_clips")
        result = clipper.cut(timestamp=60.0)
        assert result.success is False
        assert "not found" in result.error.lower() or "ffmpeg" in result.error.lower()

    def test_custom_output_name(self):
        cmd = build_ffmpeg_cut_cmd(
            input_path="in.mp4",
            output_path="/out/my_clip.mp4",
            start=0,
            duration=30,
        )
        assert cmd[-1] == "/out/my_clip.mp4"


class TestClipResult:
    def test_success_result(self):
        r = ClipResult(output_path="clip.mp4", start_time=100, duration=60, success=True)
        assert r.success is True
        assert r.error == ""

    def test_error_result(self):
        r = ClipResult(output_path="", start_time=0, duration=0, success=False, error="fail")
        assert r.success is False
        assert r.error == "fail"
