"""Tests for kickforge_core.cli module."""

import os
import shutil
import tempfile

import pytest

from kickforge_core.cli import _init_project


class TestCLIInit:
    @pytest.fixture
    def tmpdir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_init_creates_files(self, tmpdir):
        project_path = os.path.join(tmpdir, "test-bot")
        _init_project(project_path)

        assert os.path.isdir(project_path)
        assert os.path.isfile(os.path.join(project_path, "config.yaml"))
        assert os.path.isfile(os.path.join(project_path, "bot.py"))
        assert os.path.isfile(os.path.join(project_path, ".gitignore"))

    def test_init_config_content(self, tmpdir):
        project_path = os.path.join(tmpdir, "test-bot")
        _init_project(project_path)

        with open(os.path.join(project_path, "config.yaml")) as f:
            content = f.read()

        assert "client_id" in content
        assert "client_secret" in content
        assert "webhook" in content
        assert "port: 8420" in content

    def test_init_bot_content(self, tmpdir):
        project_path = os.path.join(tmpdir, "test-bot")
        _init_project(project_path)

        with open(os.path.join(project_path, "bot.py")) as f:
            content = f.read()

        assert "from kickforge_core import KickApp" in content
        assert "@app.on" in content

    def test_init_gitignore(self, tmpdir):
        project_path = os.path.join(tmpdir, "test-bot")
        _init_project(project_path)

        with open(os.path.join(project_path, ".gitignore")) as f:
            content = f.read()

        assert "__pycache__" in content
        assert "config.yaml" in content

    def test_init_idempotent(self, tmpdir):
        """Running init twice should not crash."""
        project_path = os.path.join(tmpdir, "test-bot")
        _init_project(project_path)
        _init_project(project_path)  # Should not raise
        assert os.path.isfile(os.path.join(project_path, "config.yaml"))
