"""Tests for the rerender_oversized_archives command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from model_bakery import baker

from core.models.render_queue.ffmpeg import RenderQueueItemArchive


@pytest.fixture()
def archived_game(db, tmp_path):
    """A game whose archive file exists on disk."""

    def make(height: int, size: int = 1_000_000, quality: str = "high"):
        path = tmp_path / f"archive_{height}_{quality}_{size}.mp4"
        path.write_bytes(b"0" * size)
        video = baker.make("core.Video", name="a game")
        game = baker.make("core.Game", archive_video=video, files=[])
        baker.make(
            "core.VideoFile",
            video=video,
            quality=quality,
            format="mp4",
            path=str(path),
            size=size,
        )
        return game, path

    return make


@pytest.fixture()
def heights(monkeypatch):
    """Stub ffprobe: map a path to the height it reports."""
    by_path: dict[str, int | None] = {}
    monkeypatch.setattr(
        RenderQueueItemArchive,
        "_source_video_height",
        classmethod(lambda cls, path: by_path.get(str(path))),
    )
    return by_path


def run(*args) -> str:
    out = StringIO()
    call_command("rerender_oversized_archives", *args, stdout=out)
    return out.getvalue()


class TestSelection:
    def test_a_4k_archive_is_listed(self, archived_game, heights):
        game, path = archived_game(2160)
        heights[str(path)] = 2160

        assert f"game {game.pk:5d}" in run()

    def test_a_1080p_archive_is_left_alone(self, archived_game, heights):
        _, path = archived_game(1080)
        heights[str(path)] = 1080

        assert "Aucune archive" in run()

    def test_an_unreadable_archive_is_left_alone(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = None

        assert "Aucune archive" in run()

    def test_a_missing_file_is_skipped(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160
        Path(path).unlink()

        assert "Aucune archive" in run()

    def test_the_biggest_comes_first(self, archived_game, heights):
        small_game, small = archived_game(2160, size=1000)
        big_game, big = archived_game(2160, size=9000)
        heights.update({str(small): 2160, str(big): 2160})

        output = run()

        assert output.index(f"game {big_game.pk:5d}") < output.index(
            f"game {small_game.pk:5d}"
        )

    def test_limit_caps_the_list(self, archived_game, heights):
        for size in (1000, 2000, 3000):
            _, path = archived_game(2160, size=size)
            heights[str(path)] = 2160

        assert run("--limit", "2").count("game ") == 2


class TestDryRun:
    def test_nothing_is_queued_without_apply(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160

        run()

        assert RenderQueueItemArchive.objects.count() == 0

    def test_it_says_it_is_a_preview(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160

        assert "--apply" in run()

    def test_it_estimates_what_would_be_reclaimed(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160

        assert "récupérés" in run()


class TestApply:
    def test_it_queues_a_render(self, archived_game, heights):
        game, path = archived_game(2160)
        heights[str(path)] = 2160

        run("--apply")

        assert RenderQueueItemArchive.objects.filter(game=game).count() == 1

    def test_it_keeps_the_existing_quality_as_preset(self, archived_game, heights):
        game, path = archived_game(2160, quality="high")
        heights[str(path)] = 2160

        run("--apply")

        assert RenderQueueItemArchive.objects.get(game=game).preset == "high"

    def test_the_preset_can_be_overridden(self, archived_game, heights):
        game, path = archived_game(2160, quality="high")
        heights[str(path)] = 2160

        run("--apply", "--preset", "archive")

        assert RenderQueueItemArchive.objects.get(game=game).preset == "archive"

    def test_it_names_the_file_left_behind(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160

        assert str(path) in run("--apply")

    def test_it_does_not_delete_anything(self, archived_game, heights):
        _, path = archived_game(2160)
        heights[str(path)] = 2160

        run("--apply")

        assert Path(path).exists()
