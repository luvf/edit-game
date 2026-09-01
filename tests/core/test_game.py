"""Tests for core.models.game.Game."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from model_bakery import baker

from core.models.render_queue.ffmpeg import RenderQueueItemArchive
from core.models.video import Video, VideoFile


class TestGetSourceFiles:
    def test_no_archive_video_returns_rush_paths(self, game):
        expected = [
            Path(game.tournament.media_path) / "rushs" / name for name in game.files
        ]
        assert game.get_source_files() == expected

    def test_archive_video_used_when_available(self, game, tmp_path):
        video = baker.make("core.Video", name="archive")
        archive_file = tmp_path / "archive.mp4"
        archive_file.write_bytes(b"archive-bytes")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(archive_file),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        assert game.get_source_files() == [archive_file]

    def test_falls_back_to_rush_when_archive_file_missing_on_disk(self, game, tmp_path):
        video = baker.make("core.Video", name="archive")
        missing_path = tmp_path / "gone.mp4"
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(missing_path),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        expected = [
            Path(game.tournament.media_path) / "rushs" / name for name in game.files
        ]
        assert game.get_source_files() == expected

    def test_force_rush_uses_rush_files_when_present_even_with_archive(
        self, game, tmp_path, rush_files_factory
    ):
        rush_paths = rush_files_factory(game)

        video = baker.make("core.Video", name="archive")
        archive_file = tmp_path / "archive.mp4"
        archive_file.write_bytes(b"archive-bytes")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(archive_file),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        assert game.get_source_files(force_rush=True) == rush_paths

    def test_force_rush_falls_back_when_rush_files_missing(self, game, tmp_path):
        video = baker.make("core.Video", name="archive")
        archive_file = tmp_path / "archive.mp4"
        archive_file.write_bytes(b"archive-bytes")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(archive_file),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        # rush files were never created on disk
        assert game.get_source_files(force_rush=True) == [archive_file]


class TestEnsureVideo:
    def test_creates_video_when_missing(self, game):
        assert game.video_proxy is None
        game.ensure_video()
        assert isinstance(game.video_proxy, Video)
        game.refresh_from_db()
        assert game.video_proxy is not None

    def test_is_idempotent(self, game):
        game.ensure_video()
        first = game.video_proxy
        game.ensure_video()
        assert game.video_proxy_id == first.id


class TestEnsureArchiveVideo:
    def test_creates_archive_video_when_missing(self, game):
        assert game.archive_video is None
        video = game.ensure_archive_video()
        assert video.name == f"archive{game.name}"
        game.refresh_from_db()
        assert game.archive_video_id == video.id

    def test_returns_existing_archive_video(self, game):
        video = baker.make("core.Video")
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        assert game.ensure_archive_video() == video


class TestJsonRoundtrip:
    def test_set_and_get_json(self, game):
        game.set_json({"a": 1, "b": [1, 2, 3]})

        assert game.get_json() == {"a": 1, "b": [1, 2, 3]}


class TestEnqueueProxyRender:
    def test_invalid_preset_raises(self, game):
        with pytest.raises(ValueError, match="Preset must be"):
            game.enqueue_proxy_render(preset="ultra")

    def test_creates_item_and_ensures_video(self, game):
        assert game.video_proxy is None

        item = game.enqueue_proxy_render(preset="low")

        assert item.game == game
        assert item.preset == "low"
        assert item.status == item.Status.CREATED
        game.refresh_from_db()
        assert game.video_proxy is not None


class TestEnqueueArchiveRender:
    def test_creates_item(self, game):
        item = game.enqueue_archive_render(preset="high")

        assert item.game == game
        assert item.preset == "high"

    def test_conflicts_when_pending_item_already_exists(self, game):
        game.enqueue_archive_render(preset="high")

        with pytest.raises(ValidationError) as exc_info:
            game.enqueue_archive_render(preset="high")
        assert exc_info.value.archive_video_id == game.archive_video_id

    def test_defaults_to_the_archive_preset(self, game):
        item = game.enqueue_archive_render()

        assert item.preset == RenderQueueItemArchive.DEFAULT_PRESET

    def test_force_creates_a_second_item_despite_conflict(self, game):
        first = game.enqueue_archive_render(preset="high")

        second = game.enqueue_archive_render(preset="high", force=True)

        assert first.pk != second.pk
        assert (
            RenderQueueItemArchive.objects.filter(game=game, preset="high").count()
            == 2
        )

    def test_conflicts_when_archive_file_already_exists_on_disk(self, game, tmp_path):
        video = baker.make("core.Video", name="archive")
        archive_file = tmp_path / "archive.mp4"
        archive_file.write_bytes(b"x")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(archive_file),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        with pytest.raises(ValidationError) as exc_info:
            game.enqueue_archive_render(preset="high")
        assert exc_info.value.archive_video_id == video.id

    def test_force_bypasses_existing_archive_file_conflict(self, game, tmp_path):
        video = baker.make("core.Video", name="archive")
        archive_file = tmp_path / "archive.mp4"
        archive_file.write_bytes(b"x")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(archive_file),
        )
        game.archive_video = video
        game.save(update_fields=["archive_video"])

        item = game.enqueue_archive_render(preset="high", force=True)

        assert item.game == game
