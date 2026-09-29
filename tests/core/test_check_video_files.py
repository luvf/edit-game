"""Tests for the check_video_files management command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from core.models.video import VideoFile


@pytest.fixture()
def stale_row(game, tmp_path):
    """A row whose stored path leads nowhere, with the file where it belongs."""
    video = baker.make("core.Video", name="proxy")
    game.video_proxy = video
    game.save(update_fields=["video_proxy"])
    video.refresh_from_db()
    row = VideoFile.objects.create(
        video=video,
        quality=VideoFile.Quality.LOW,
        format=VideoFile.Format.MP4,
    )
    expected = row.expected_path()
    row.path = str(tmp_path / "old_drive" / "gone.mp4")
    row.save(update_fields=["path"])
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_bytes(b"12345")
    return row, expected


def run(*args: str) -> str:
    """Run the command and return what it printed."""
    out = StringIO()
    call_command("check_video_files", *args, stdout=out, stderr=out)
    return out.getvalue()


class TestCheckVideoFiles:
    def test_regenerates_the_path_and_stores_it(self, stale_row, monkeypatch):
        row, expected = stale_row
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))

        output = run()

        assert "chemin perime, repare" in output
        row.refresh_from_db()
        assert row.path == str(expected)
        assert row.fps == 25.0
        assert row.size == 5

    def test_dry_run_changes_nothing(self, stale_row, monkeypatch):
        row, _ = stale_row
        stale_path = row.path
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))

        output = run("--dry-run")

        assert "Aurait mis a jour" in output
        row.refresh_from_db()
        assert row.path == stale_path
        assert row.fps is None

    def test_leaves_a_row_it_cannot_repair(self, game, tmp_path):
        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()
        row = VideoFile.objects.create(
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )
        stale_path = row.path

        output = run()

        assert "fichier absent du disque" in output
        row.refresh_from_db()
        assert row.path == stale_path
