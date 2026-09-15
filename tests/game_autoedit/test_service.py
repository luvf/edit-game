"""Tests for the caching guards in game_autoedit.service.

Everything the proposal needs is built once and read from the cache afterwards.
These tests cover the one question that makes that safe: was the cached thing
computed from the audio that is on disk now?
"""

from __future__ import annotations

import os

import numpy as np
import pytest
import soundfile as sf

from game_autoedit.config import SAMPLE_RATE, Paths
from game_autoedit.data.beats import envelope_path
from game_autoedit.service import _derived_from, _ensure_envelope


@pytest.fixture()
def paths(tmp_path):
    built = Paths(root=tmp_path)
    built.ensure()
    return built


def _track(paths, game_id, *, seconds=2.0):
    """Write a cached audio track, as the extraction would have."""
    samples = np.sin(
        2 * np.pi * 220 * np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    ).astype(np.float32)
    path = paths.audio_path(game_id)
    sf.write(path, samples, SAMPLE_RATE, subtype="PCM_16")
    return path


class TestDerivedFrom:
    def test_a_missing_cache_is_not_current(self, tmp_path):
        audio = tmp_path / "game_1.wav"
        audio.write_bytes(b"")

        assert not _derived_from(tmp_path / "absent.npy", audio)

    def test_a_cache_written_after_the_track_is_current(self, tmp_path):
        audio = tmp_path / "game_1.wav"
        audio.write_bytes(b"")
        cached = tmp_path / "game_1.npy"
        cached.write_bytes(b"")

        assert _derived_from(cached, audio)

    def test_a_track_extracted_again_invalidates_the_cache(self, tmp_path):
        cached = tmp_path / "game_1.npy"
        cached.write_bytes(b"")
        audio = tmp_path / "game_1.wav"
        audio.write_bytes(b"")
        # A game first proposed from its rushes, re-extracted from its archive.
        stamp = cached.stat().st_mtime_ns + 10**9
        os.utime(audio, ns=(stamp, stamp))

        assert not _derived_from(cached, audio)


class TestEnsureEnvelope:
    def test_computes_and_caches_the_envelope(self, paths):
        _track(paths, 1)

        envelope = _ensure_envelope(1, paths)

        assert envelope is not None
        assert envelope_path(paths.beats, 1).exists()

    def test_reuses_the_cached_envelope(self, paths):
        _track(paths, 1)
        _ensure_envelope(1, paths)
        stamp = envelope_path(paths.beats, 1).stat().st_mtime_ns

        _ensure_envelope(1, paths)

        assert envelope_path(paths.beats, 1).stat().st_mtime_ns == stamp

    def test_recomputes_it_when_the_track_was_extracted_again(self, paths):
        _track(paths, 1, seconds=2.0)
        first = _ensure_envelope(1, paths)
        _track(paths, 1, seconds=4.0)

        second = _ensure_envelope(1, paths)

        assert second is not None
        assert len(second) > len(first)

    def test_no_track_means_no_envelope(self, paths):
        assert _ensure_envelope(404, paths) is None
