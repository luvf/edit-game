"""Tests for game_autoedit.data.audio."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from game_autoedit.config import AUDIO_QUALITY, RUSH_QUALITY
from game_autoedit.data.audio import (
    AudioExtractionError,
    _extract_command,
    _marker_path,
    audio_info,
    build_audio_cache,
    extract_audio,
    probe_fps,
    read_window,
)
from game_autoedit.data.catalog import LabeledGame

RATE = 16000


@pytest.fixture()
def wav(tmp_path):
    path = tmp_path / "game_42.wav"
    samples = np.linspace(-1.0, 1.0, RATE * 10, dtype=np.float32)
    sf.write(path, samples, RATE, subtype="PCM_16")
    return path


class TestAudioInfo:
    def test_reads_duration_and_rate(self, wav):
        info = audio_info(wav)

        assert info is not None
        assert info.sample_rate == RATE
        assert info.duration == pytest.approx(10.0, abs=0.01)

    def test_reads_the_game_id_from_the_filename(self, wav):
        assert audio_info(wav).game_id == 42

    def test_missing_file_returns_none(self, tmp_path):
        assert audio_info(tmp_path / "game_1.wav") is None

    def test_unreadable_file_returns_none(self, tmp_path):
        path = tmp_path / "game_1.wav"
        path.write_text("not audio")

        assert audio_info(path) is None


class TestReadWindow:
    def test_returns_the_requested_length(self, wav):
        chunk = read_window(wav, 1.0, 2.0, sample_rate=RATE)

        assert len(chunk) == RATE * 2
        assert chunk.dtype == np.float32

    def test_reads_from_the_right_offset(self, wav):
        whole = read_window(wav, 0.0, 10.0, sample_rate=RATE)
        chunk = read_window(wav, 5.0, 1.0, sample_rate=RATE)

        assert chunk == pytest.approx(whole[RATE * 5 : RATE * 6], abs=1e-4)

    def test_pads_a_window_running_past_the_end(self, wav):
        chunk = read_window(wav, 9.0, 3.0, sample_rate=RATE)

        assert len(chunk) == RATE * 3
        assert chunk[-RATE:] == pytest.approx(np.zeros(RATE))

    def test_window_entirely_past_the_end_is_silent(self, wav):
        chunk = read_window(wav, 20.0, 1.0, sample_rate=RATE)

        assert chunk == pytest.approx(np.zeros(RATE))


def _media(path, *, seconds, frequency, rate=48000, channels=2, fps=30):
    """Render a tiny video with a sine tone, as a rush would come off a camera."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate={rate}:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=64x64:rate={fps}:duration={seconds}",
            "-ac",
            str(channels),
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class TestExtractCommand:
    def test_a_single_source_needs_no_filter(self, tmp_path):
        command = _extract_command(
            [Path("/a/archive.mp4")],
            tmp_path / "out.wav",
            sample_rate=RATE,
            channels=1,
        )

        assert "-filter_complex" not in command
        assert command.count("-i") == 1

    def test_several_sources_are_concatenated_in_order(self, tmp_path):
        command = _extract_command(
            [Path("/a/one.mp4"), Path("/a/two.mp4"), Path("/a/three.mp4")],
            tmp_path / "out.wav",
            sample_rate=RATE,
            channels=2,
        )
        graph = command[command.index("-filter_complex") + 1]

        assert command.index("/a/one.mp4") < command.index("/a/two.mp4")
        assert "[a0][a1][a2]concat=n=3:v=0:a=1[out]" in graph
        assert command[command.index("-map") + 1] == "[out]"

    def test_every_segment_is_normalised_before_the_concat(self, tmp_path):
        # The concat filter refuses segments that disagree on rate or layout,
        # and two cameras regularly do.
        command = _extract_command(
            [Path("/a/one.mp4"), Path("/a/two.mp4")],
            tmp_path / "out.wav",
            sample_rate=RATE,
            channels=2,
        )
        graph = command[command.index("-filter_complex") + 1]

        assert graph.count(f"aformat=sample_rates={RATE}:channel_layouts=stereo") == 2


class TestExtractAudio:
    def test_decodes_one_file(self, tmp_path):
        source = _media(tmp_path / "archive.mp4", seconds=2, frequency=440)
        destination = tmp_path / "game_1.wav"

        extract_audio(source, destination, sample_rate=RATE, channels=1)

        info = audio_info(destination)
        assert info.channels == 1
        assert info.sample_rate == RATE
        assert info.duration == pytest.approx(2.0, abs=0.05)

    def test_concatenates_rushes_whose_profiles_differ(self, tmp_path):
        first = _media(tmp_path / "GH010001.MP4", seconds=2, frequency=440)
        second = _media(
            tmp_path / "GH020001.MP4",
            seconds=1,
            frequency=880,
            rate=44100,
            channels=1,
        )
        destination = tmp_path / "game_2.wav"

        extract_audio([first, second], destination, sample_rate=RATE, channels=2)

        info = audio_info(destination)
        assert info.channels == 2
        assert info.duration == pytest.approx(3.0, abs=0.1)

    def test_the_timeline_is_the_rushes_end_to_end(self, tmp_path):
        # What makes the fallback usable: the second rush starts exactly where
        # the first ends, as it does in the archive.
        first = _media(tmp_path / "GH010001.MP4", seconds=2, frequency=440)
        second = _media(tmp_path / "GH020001.MP4", seconds=2, frequency=0)
        destination = tmp_path / "game_3.wav"

        extract_audio([first, second], destination, sample_rate=RATE, channels=1)

        whole = read_window(destination, 0.0, 4.0, sample_rate=RATE)
        tone = np.abs(whole[: RATE * 2 - 100]).mean()
        silence = np.abs(whole[RATE * 2 + 100 :]).mean()

        assert tone > 100 * silence

    def test_leaves_nothing_behind_when_ffmpeg_fails(self, tmp_path):
        broken = tmp_path / "broken.mp4"
        broken.write_text("not a video")
        destination = tmp_path / "game_4.wav"

        with pytest.raises(AudioExtractionError, match="broken.mp4"):
            extract_audio([broken], destination)

        assert not destination.exists()
        assert not list(tmp_path.glob("*.partial.wav"))

    def test_refuses_an_empty_source_list(self, tmp_path):
        with pytest.raises(AudioExtractionError, match="aucune source"):
            extract_audio([], tmp_path / "game_5.wav")


class TestProbeFps:
    def test_reads_the_rate_off_the_file(self, tmp_path):
        source = _media(tmp_path / "rush.mp4", seconds=1, frequency=440, fps=25)

        assert probe_fps(source) == pytest.approx(25.0)

    def test_unreadable_file_returns_none(self, tmp_path):
        path = tmp_path / "nope.mp4"
        path.write_text("not a video")

        assert probe_fps(path) is None


def _game(game_id, sources, *, quality):
    """A catalog entry standing in for whatever the database would have said."""
    return LabeledGame(
        game_id=game_id,
        name=f"game {game_id}",
        slug=f"game-{game_id}",
        tournament="tournoi",
        cut_id=0,
        cut_type="ML",
        cut_json_path=Path("/nowhere.json"),
        audio_sources=tuple(sources),
        fps=59.94,
        quality=quality,
    )


class TestBuildAudioCache:
    @pytest.fixture()
    def rushes(self, tmp_path):
        return [
            _media(tmp_path / "GH010001.MP4", seconds=1, frequency=440),
            _media(tmp_path / "GH020001.MP4", seconds=1, frequency=880),
        ]

    def test_extracts_and_records_where_the_track_came_from(self, tmp_path, rushes):
        game = _game(7, rushes, quality=RUSH_QUALITY)

        _, cached, error = next(
            iter(build_audio_cache([game], cache_dir=tmp_path / "cache"))
        )
        assert error is None
        assert cached.duration == pytest.approx(2.0, abs=0.1)
        marker = json.loads(_marker_path(cached.path).read_text())
        assert marker == {
            "quality": RUSH_QUALITY,
            "sources": [str(rush) for rush in rushes],
        }

    def test_reuses_a_track_extracted_from_the_same_sources(self, tmp_path, rushes):
        game = _game(7, rushes, quality=RUSH_QUALITY)
        cache = tmp_path / "cache"
        first = next(iter(build_audio_cache([game], cache_dir=cache)))[1]
        stamp = first.path.stat().st_mtime_ns

        list(build_audio_cache([game], cache_dir=cache))

        assert first.path.stat().st_mtime_ns == stamp

    def test_re_extracts_when_the_game_is_read_from_another_source(
        self, tmp_path, rushes
    ):
        # The case that would otherwise feed rush audio to training: a game
        # proposed from its rushes, archived afterwards, then trained on.
        cache = tmp_path / "cache"
        proposed = _game(7, rushes, quality=RUSH_QUALITY)
        cached = next(iter(build_audio_cache([proposed], cache_dir=cache)))[1]
        stamp = cached.path.stat().st_mtime_ns

        archive = _media(tmp_path / "archive.mp4", seconds=3, frequency=220)
        archived = _game(7, [archive], quality=AUDIO_QUALITY)
        _, rebuilt, error = next(iter(build_audio_cache([archived], cache_dir=cache)))

        assert error is None
        assert rebuilt.path.stat().st_mtime_ns != stamp
        assert rebuilt.duration == pytest.approx(3.0, abs=0.1)

    def test_a_track_cached_before_the_sidecar_existed_is_trusted(
        self, tmp_path, rushes
    ):
        # Re-extracting the tracks built before provenance was recorded would
        # cost a night to learn what is already known: they are all archives.
        cache = tmp_path / "cache"
        game = _game(7, rushes, quality=RUSH_QUALITY)
        cached = next(iter(build_audio_cache([game], cache_dir=cache)))[1]
        _marker_path(cached.path).unlink()
        stamp = cached.path.stat().st_mtime_ns

        list(build_audio_cache([game], cache_dir=cache))

        assert cached.path.stat().st_mtime_ns == stamp
