"""Shared pytest fixtures: filesystem isolation and common model factories."""

from __future__ import annotations

from pathlib import Path

import pytest
from model_bakery import baker


@pytest.fixture(autouse=True)
def _isolated_media_paths(settings, tmp_path):
    """Redirect filesystem-touching settings to a per-test tmp directory.

    `settings.py` points by default at real network mounts (`/mnt/video/...`,
    `/mnt/jugger/...`) and the dev `medias/` dir. No test should ever read or
    write those; this fixture is autouse so every test gets isolated paths.
    """
    media_root = tmp_path / "medias"
    media_root.mkdir(parents=True, exist_ok=True)
    settings.MEDIA_ROOT = str(media_root)
    settings.TOURNAMENTS_BASE_DIR = tmp_path / "video_source"
    settings.TOURNAMENTS_ARCHIVE_DIR = tmp_path / "video_archive"
    settings.AUTOEDIT_CACHE = str(tmp_path / "autoedit_cache")


@pytest.fixture()
def api_client():
    """A DRF APIClient for hitting the real router endpoints."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture()
def team1(db):
    """A first team fixture."""
    return baker.make("core.Team", name="Alpha", short_name="ALP")


@pytest.fixture()
def team2(db):
    """A second team fixture."""
    return baker.make("core.Team", name="Beta", short_name="BET")


@pytest.fixture()
def tournament(db, settings, tmp_path):
    """A Tournament whose media_path resolves inside tmp_path.

    `Tournament.drive_dir`'s model-level default is baked in at import time
    from `settings.TOURNAMENTS_BASE_DIR`, so overriding `settings` alone does
    not affect it: `drive_dir` must be set explicitly on every Tournament
    used in tests that touch the filesystem.
    """
    tournament_dir = "test-tournament"
    drive_dir = tmp_path / "video_source"
    (drive_dir / tournament_dir / "rushs").mkdir(parents=True, exist_ok=True)
    return baker.make(
        "core.Tournament",
        drive_dir=str(drive_dir),
        tournament_dir=tournament_dir,
    )


@pytest.fixture()
def game(db, tournament, team1, team2):
    """A Game fixture with two rush files declared (not necessarily on disk)."""
    return baker.make(
        "core.Game",
        tournament=tournament,
        team1=team1,
        team2=team2,
        files=["GH010001.MP4", "GH020001.MP4"],
        archive_video=None,
    )


@pytest.fixture()
def rush_files_factory():
    """Return a callable that materializes a Game's declared rush files on disk."""

    def _make(game_obj, *, content: bytes = b"fake-video-bytes") -> list[Path]:
        rushs_dir = Path(game_obj.tournament.media_path) / "rushs"
        rushs_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in game_obj.files:
            path = rushs_dir / name
            path.write_bytes(content)
            paths.append(path)
        return paths

    return _make
