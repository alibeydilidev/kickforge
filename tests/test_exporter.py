"""Tests for kickforge_clip.exporter module."""

import os
import tempfile
import shutil

import pytest

from kickforge_clip.detector import HeatMoment
from kickforge_clip.exporter import ClipExporter, ExportedClip


class TestClipExporter:
    @pytest.fixture
    def tmpdir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def sample_clips(self, tmpdir):
        """Create dummy clip files and corresponding moments."""
        moments = [
            HeatMoment(timestamp=100, score=3.5, messages_per_second=2.0, unique_chatters=5),
            HeatMoment(timestamp=200, score=8.2, messages_per_second=5.0, unique_chatters=12),
            HeatMoment(timestamp=300, score=1.1, messages_per_second=0.5, unique_chatters=2),
            HeatMoment(timestamp=400, score=6.0, messages_per_second=3.0, unique_chatters=8),
        ]
        paths = []
        for i in range(4):
            p = os.path.join(tmpdir, f"clip_{i}.mp4")
            with open(p, "w") as f:
                f.write(f"fake clip {i}")
            paths.append(p)
        return moments, paths

    def test_export_ranks_by_score(self, tmpdir, sample_clips):
        moments, paths = sample_clips
        export_dir = os.path.join(tmpdir, "export")
        exporter = ClipExporter(output_dir=export_dir)
        exported = exporter.export(moments, paths, top_n=10)

        assert len(exported) == 4
        # First should be highest score
        assert exported[0].score == 8.2
        assert exported[0].rank == 1
        assert exported[1].score == 6.0
        assert exported[1].rank == 2

    def test_export_top_n(self, tmpdir, sample_clips):
        moments, paths = sample_clips
        export_dir = os.path.join(tmpdir, "export")
        exporter = ClipExporter(output_dir=export_dir)
        exported = exporter.export(moments, paths, top_n=2)

        assert len(exported) == 2
        assert exported[0].score == 8.2
        assert exported[1].score == 6.0

    def test_export_creates_files(self, tmpdir, sample_clips):
        moments, paths = sample_clips
        export_dir = os.path.join(tmpdir, "export")
        exporter = ClipExporter(output_dir=export_dir)
        exported = exporter.export(moments, paths, top_n=2)

        for clip in exported:
            assert os.path.isfile(clip.path)

    def test_export_file_naming(self, tmpdir, sample_clips):
        moments, paths = sample_clips
        export_dir = os.path.join(tmpdir, "export")
        exporter = ClipExporter(output_dir=export_dir)
        exported = exporter.export(moments, paths, top_n=1)

        name = os.path.basename(exported[0].path)
        # Format: {date}_{rank}_{score}.mp4
        assert name.endswith(".mp4")
        assert "_1_" in name  # rank 1
        assert "_8" in name   # score ~8

    def test_export_mismatched_lengths(self, tmpdir):
        exporter = ClipExporter(output_dir=tmpdir)
        with pytest.raises(ValueError):
            exporter.export([HeatMoment(0, 1, 0, 0)], [], top_n=1)

    def test_rank_moments(self):
        moments = [
            HeatMoment(0, 3.0, 0, 0),
            HeatMoment(0, 9.0, 0, 0),
            HeatMoment(0, 1.0, 0, 0),
        ]
        ranked = ClipExporter.rank_moments(moments)
        assert ranked[0].score == 9.0
        assert ranked[1].score == 3.0
        assert ranked[2].score == 1.0

    def test_export_skips_missing_clips(self, tmpdir):
        moments = [
            HeatMoment(0, 5.0, 0, 0),
            HeatMoment(0, 3.0, 0, 0),
        ]
        real = os.path.join(tmpdir, "real.mp4")
        with open(real, "w") as f:
            f.write("data")

        export_dir = os.path.join(tmpdir, "export")
        exporter = ClipExporter(output_dir=export_dir)
        exported = exporter.export(moments, [real, "/nonexistent.mp4"], top_n=10)
        assert len(exported) == 1
