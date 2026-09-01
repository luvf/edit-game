"""Tests for game_autoedit.data.catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from game_autoedit.config import ARCHIVE_QUALITIES, AUDIO_QUALITY, DEFAULT_FPS
from game_autoedit.data.catalog import _audio_source, pick_cut


@dataclass
class FakeFile:
    path: str
    exists_on_disk: bool
    fps: float | None = None


class FakeVideo:
    def __init__(self, files: dict[str, FakeFile]) -> None:
        self.files = files

    def get_file(self, quality: str, file_format: str = "mp4") -> FakeFile:
        if quality not in self.files:
            raise FileNotFoundError(quality)
        return self.files[quality]


@dataclass
class FakeGame:
    archive_video: FakeVideo | None = None
    video_proxy: FakeVideo | None = None


@dataclass
class FakeCut:
    type_cut: str
    pk: int


class TestArchiveQualities:
    def test_archive_is_preferred_over_high(self):
        assert ARCHIVE_QUALITIES.index("archive") < ARCHIVE_QUALITIES.index("high")

    def test_both_historical_names_are_accepted(self):
        assert set(ARCHIVE_QUALITIES) == {"archive", "high"}


class TestAudioSource:
    def test_finds_the_modern_archive(self):
        game = FakeGame(
            archive_video=FakeVideo(
                {"archive": FakeFile("/a/archive.mp4", exists_on_disk=True, fps=59.94)}
            )
        )
        source = _audio_source(game, AUDIO_QUALITY)

        assert source.path == Path("/a/archive.mp4")
        assert source.quality == "archive"
        assert source.fps == pytest.approx(59.94)

    def test_falls_back_to_the_older_high_label(self):
        # Masters rendered before the "archive" quality existed sit under
        # "high"; dropping them cost half the archived tournaments.
        game = FakeGame(
            archive_video=FakeVideo(
                {"high": FakeFile("/a/old.mp4", exists_on_disk=True)}
            )
        )
        source = _audio_source(game, AUDIO_QUALITY)

        assert source.path == Path("/a/old.mp4")
        assert source.quality == "high"

    def test_prefers_archive_when_both_are_on_disk(self):
        game = FakeGame(
            archive_video=FakeVideo(
                {
                    "archive": FakeFile("/a/new.mp4", exists_on_disk=True),
                    "high": FakeFile("/a/old.mp4", exists_on_disk=True),
                }
            )
        )

        assert _audio_source(game, AUDIO_QUALITY).path == Path("/a/new.mp4")

    def test_skips_a_row_whose_file_is_gone(self):
        game = FakeGame(
            archive_video=FakeVideo(
                {
                    "archive": FakeFile("/a/new.mp4", exists_on_disk=False),
                    "high": FakeFile("/a/old.mp4", exists_on_disk=True),
                }
            )
        )

        assert _audio_source(game, AUDIO_QUALITY).path == Path("/a/old.mp4")

    def test_reports_which_rows_exist_when_none_is_on_disk(self):
        game = FakeGame(
            archive_video=FakeVideo(
                {"high": FakeFile("/a/old.mp4", exists_on_disk=False)}
            )
        )
        source = _audio_source(game, AUDIO_QUALITY)

        assert source.path is None
        assert "high" in (source.reason or "")

    def test_reports_a_missing_row(self):
        source = _audio_source(FakeGame(archive_video=FakeVideo({})), AUDIO_QUALITY)

        assert source.path is None
        assert "en base" in (source.reason or "")

    def test_reports_a_missing_video(self):
        source = _audio_source(FakeGame(), AUDIO_QUALITY)

        assert source.path is None
        assert "rattachée" in (source.reason or "")

    def test_defaults_the_fps_when_unknown(self):
        game = FakeGame(
            archive_video=FakeVideo(
                {"archive": FakeFile("/a/new.mp4", exists_on_disk=True, fps=None)}
            )
        )

        assert _audio_source(game, AUDIO_QUALITY).fps == pytest.approx(DEFAULT_FPS)

    def test_a_non_archive_quality_has_no_fallback(self):
        game = FakeGame(
            video_proxy=FakeVideo(
                {"medium": FakeFile("/a/proxy.mp4", exists_on_disk=True)}
            )
        )

        assert _audio_source(game, "low").path is None


class TestPickCut:
    def test_prefers_a_cut_from_a_real_edit(self):
        chosen = pick_cut([FakeCut("VID", 1), FakeCut("OTIO", 2)])

        assert chosen.type_cut == "OTIO"

    def test_falls_back_to_the_reconstructed_one(self):
        assert pick_cut([FakeCut("VID", 1)]).type_cut == "VID"

    def test_ties_go_to_the_most_recent_row(self):
        assert pick_cut([FakeCut("VID", 1), FakeCut("VID", 9)]).pk == 9
