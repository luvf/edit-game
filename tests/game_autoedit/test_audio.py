"""Tests for game_autoedit.data.audio."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from game_autoedit.data.audio import audio_info, read_window

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
