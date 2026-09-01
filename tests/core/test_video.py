"""Tests for core.models.video."""

from __future__ import annotations

import pytest
from model_bakery import baker

from core.models.cut import Cut
from core.models.video import Video, VideoFile, file_exists


class TestBaseFilename:
    def test_uses_slugified_name(self):
        video = Video(name="My Cool Video")
        assert video.base_filename == f"my-cool-video_{video.uuid}"

    def test_defaults_to_video_when_no_name(self):
        video = Video(name="")
        assert video.base_filename == f"video_{video.uuid}"


class TestValidateQuality:
    def test_valid_quality_returns_false(self):
        assert VideoFile.validate_quality(quality="low") is False

    def test_invalid_quality_returns_true_without_exception(self):
        assert VideoFile.validate_quality(quality="ultra") is True

    def test_invalid_quality_raises_when_requested(self):
        with pytest.raises(ValueError, match="Quality must be one of"):
            VideoFile.validate_quality(quality="ultra", throw_exception=True)


class TestValidateFormat:
    def test_valid_format_returns_false(self):
        assert VideoFile.validate_format(file_format="mp4") is False

    def test_invalid_format_raises_when_requested(self):
        with pytest.raises(ValueError, match="Format must be one of"):
            VideoFile.validate_format(file_format="avi", throw_exception=True)


class TestBasePath:
    def test_game_proxy_video_uses_proxy_subdir(self, game):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()

        assert video.base_path == game.tournament.media_path / "proxy"

    def test_cut_rendered_video_uses_generated_rendered_subdir(self, game):
        video = baker.make("core.Video")
        cut = Cut.objects.create(game=game, name="cut1", type_cut="MAN")
        cut.rendered_video = video
        cut.save(update_fields=["rendered_video"])
        video.refresh_from_db()

        assert video.base_path == game.tournament.media_path / "generated_rendered"

    def test_archive_video_uses_archive_subdir(self, game):
        video = baker.make("core.Video")
        game.archive_video = video
        game.save(update_fields=["archive_video"])
        video.refresh_from_db()

        assert video.base_path == game.tournament.media_path / "archive"

    def test_unlinked_video_raises(self, db):
        video = baker.make("core.Video")
        with pytest.raises(ValueError, match="not linked to a game"):
            _ = video.base_path


class TestVideoFileSaveAutoPath:
    def test_fills_path_from_expected_filename_when_missing(self, game):
        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()

        video_file = VideoFile(
            video=video, quality=VideoFile.Quality.LOW, format=VideoFile.Format.MP4
        )
        video_file.save()

        assert video_file.path == str(video.base_path / video.expected_filename("low"))

    def test_does_not_override_an_explicit_path(self, game):
        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])

        video_file = VideoFile(
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/custom/path.mp4",
        )
        video_file.save()

        assert video_file.path == "/custom/path.mp4"


class TestHasQualityAndGetFile:
    def test_has_quality_false_when_no_file(self, game):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])

        assert video.has_quality("low") is False

    def test_get_file_raises_when_missing(self, db):
        video = baker.make("core.Video")

        with pytest.raises(FileNotFoundError):
            video.get_file("low")

    def test_get_file_returns_existing_row(self, db):
        video = baker.make("core.Video")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )

        assert video.has_quality("low") is True
        assert video.get_file("low") == video_file


class TestPathForQuality:
    def test_returns_real_path_when_file_exists(self, db, tmp_path):
        video = baker.make("core.Video")
        real_file = tmp_path / "file.mp4"
        real_file.write_bytes(b"x")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.ARCHIVE,
            format=VideoFile.Format.MP4,
            path=str(real_file),
        )

        assert video.path_for_quality("archive") == real_file

    def test_raises_when_row_missing(self, db):
        video = baker.make("core.Video")

        with pytest.raises(FileNotFoundError):
            video.path_for_quality("archive")


class TestRealPath:
    def test_raises_when_no_path_stored(self, db):
        video = baker.make("core.Video")
        video_file = VideoFile(
            video=video, quality=VideoFile.Quality.LOW, format=VideoFile.Format.MP4
        )

        with pytest.raises(FileNotFoundError, match="no stored path"):
            _ = video_file.real_path

    def test_raises_when_file_missing_on_disk(self, db, tmp_path):
        video = baker.make("core.Video")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=str(tmp_path / "gone.mp4"),
        )

        with pytest.raises(FileNotFoundError, match="does not exist"):
            _ = video_file.real_path

    def test_returns_path_when_file_exists(self, db, tmp_path):
        video = baker.make("core.Video")
        real_file = tmp_path / "there.mp4"
        real_file.write_bytes(b"x")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=str(real_file),
        )

        assert video_file.real_path == real_file


class TestSetRealPath:
    def test_persists_path_and_size(self, db, tmp_path):
        video = baker.make("core.Video")
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"12345")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )

        video_file.set_real_path(real_file)

        video_file.refresh_from_db()
        assert video_file.path == str(real_file)
        assert video_file.size == 5

    def test_size_none_when_file_missing(self, db, tmp_path):
        video = baker.make("core.Video")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )

        video_file.set_real_path(tmp_path / "missing.mp4")

        assert video_file.size is None


class TestVideoFileUrl:
    def test_empty_string_when_file_missing(self, game):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path="/does/not/exist.mp4",
        )

        assert video_file.url == ""

    def test_builds_url_from_video_base_url_when_file_exists(self, game, tmp_path):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        real_file = tmp_path / "out.mp4"
        real_file.write_bytes(b"x")
        video_file = baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=str(real_file),
        )

        assert video_file.url == f"{video.base_url}/{real_file.name}"


class TestCheckFile:
    def _video_file(self, path: str = "") -> VideoFile:
        return baker.make(
            "core.VideoFile",
            video=baker.make("core.Video"),
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=path,
        )

    def test_no_path_reports_no_path(self):
        video_file = VideoFile(quality=VideoFile.Quality.LOW, path="")

        assert video_file.check_file() == (VideoFile.FileCheck.NO_PATH, None)

    def test_missing_file_reports_missing(self, db, tmp_path):
        video_file = self._video_file(path=str(tmp_path / "gone.mp4"))

        assert video_file.check_file() == (VideoFile.FileCheck.MISSING, None)

    def test_probe_failure_keeps_stored_fps(self, db, tmp_path, monkeypatch):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")
        video_file = self._video_file(path=str(real_file))
        video_file.fps = 25.0
        video_file.save(update_fields=["fps"])
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: None))

        assert video_file.check_file() == (VideoFile.FileCheck.PROBE_FAILED, None)
        video_file.refresh_from_db()
        assert video_file.fps == 25.0

    def test_fills_missing_fps(self, db, tmp_path, monkeypatch):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")
        video_file = self._video_file(path=str(real_file))
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 50.0))

        assert video_file.check_file() == (VideoFile.FileCheck.FPS_FILLED, 50.0)
        video_file.refresh_from_db()
        assert video_file.fps == 50.0

    def test_corrects_wrong_fps(self, db, tmp_path, monkeypatch):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")
        video_file = self._video_file(path=str(real_file))
        video_file.fps = 60.0
        video_file.save(update_fields=["fps"])
        monkeypatch.setattr(
            VideoFile, "probe_fps", staticmethod(lambda path: 60000 / 1001)
        )

        outcome, probed = video_file.check_file()

        assert outcome == VideoFile.FileCheck.FPS_UPDATED
        video_file.refresh_from_db()
        assert video_file.fps == pytest.approx(probed)

    def test_matching_fps_is_left_alone(self, db, tmp_path, monkeypatch):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")
        video_file = self._video_file(path=str(real_file))
        video_file.fps = 25.0
        video_file.save(update_fields=["fps"])
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))

        assert video_file.check_file() == (VideoFile.FileCheck.OK, 25.0)

    def test_save_false_does_not_persist(self, db, tmp_path, monkeypatch):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")
        video_file = self._video_file(path=str(real_file))
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 50.0))

        video_file.check_file(save=False)

        assert video_file.fps == 50.0
        video_file.refresh_from_db()
        assert video_file.fps is None


class TestCheckFileRepairsStalePaths:
    def _video_file(self, game, tmp_path, *, quality=VideoFile.Quality.LOW):
        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()
        return baker.make(
            "core.VideoFile",
            video=video,
            quality=quality,
            format=VideoFile.Format.MP4,
            path=str(tmp_path / "old_drive" / "gone.mp4"),
        )

    def test_adopts_the_file_at_the_expected_path(self, game, tmp_path, monkeypatch):
        video_file = self._video_file(game, tmp_path)
        expected = video_file.expected_path()
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"12345")
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))

        outcome, probed = video_file.check_file()

        assert outcome == VideoFile.FileCheck.PATH_FIXED
        assert probed == 25.0
        video_file.refresh_from_db()
        assert video_file.path == str(expected)
        assert video_file.size == 5
        assert video_file.fps == 25.0

    def test_falls_back_to_the_stored_filename_in_the_current_dir(
        self, game, tmp_path, monkeypatch
    ):
        video_file = self._video_file(game, tmp_path)
        renamed = video_file.video.base_path / "gone.mp4"
        renamed.parent.mkdir(parents=True, exist_ok=True)
        renamed.write_bytes(b"x")
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 30.0))

        outcome, _ = video_file.check_file()

        assert outcome == VideoFile.FileCheck.PATH_FIXED
        video_file.refresh_from_db()
        assert video_file.path == str(renamed)

    def test_still_missing_when_nothing_is_found(self, game, tmp_path):
        video_file = self._video_file(game, tmp_path)

        outcome, _ = video_file.check_file()

        assert outcome == VideoFile.FileCheck.MISSING
        video_file.refresh_from_db()
        assert video_file.path == str(tmp_path / "old_drive" / "gone.mp4")

    def test_a_corrupt_relocated_file_is_reported_but_still_adopted(
        self, game, tmp_path, monkeypatch
    ):
        video_file = self._video_file(game, tmp_path)
        expected = video_file.expected_path()
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"truncated")
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: None))

        outcome, _ = video_file.check_file()

        assert outcome == VideoFile.FileCheck.PROBE_FAILED
        video_file.refresh_from_db()
        assert video_file.path == str(expected)

    def test_save_false_leaves_the_database_alone(self, game, tmp_path, monkeypatch):
        video_file = self._video_file(game, tmp_path)
        expected = video_file.expected_path()
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"x")
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 25.0))
        stale = video_file.path

        video_file.check_file(save=False)

        assert video_file.path == str(expected)
        video_file.refresh_from_db()
        assert video_file.path == stale


class TestFileExists:
    def test_true_for_a_real_file(self, tmp_path):
        real_file = tmp_path / "f.mp4"
        real_file.write_bytes(b"x")

        assert file_exists(real_file) is True

    def test_false_for_a_missing_file(self, tmp_path):
        assert file_exists(tmp_path / "gone.mp4") is False

    def test_false_instead_of_raising_on_a_path_too_long(self, tmp_path):
        assert file_exists(tmp_path / ("x" * 512)) is False

    def test_false_instead_of_raising_on_a_null_byte(self):
        assert file_exists("/tmp/a\x00b.mp4") is False
