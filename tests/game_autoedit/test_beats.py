"""Tests for the drum grid and for placing cuts on it."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.data.beats import (
    ENVELOPE_RATE,
    BeatGrid,
    estimate_grid,
    load_envelope,
    save_envelope,
)
from game_autoedit.data.labels import Segment
from game_autoedit.eval.decode import DecodeSpec
from game_autoedit.eval.snap import snap_segments, snap_time

PERIOD = 1.5


@pytest.fixture()
def drum_envelope():
    """An onset envelope with a beat every 1.5 s, as the archives have."""
    seconds = 120
    envelope = np.random.default_rng(0).normal(0.2, 0.05, seconds * ENVELOPE_RATE)
    for beat in np.arange(0.4, seconds, PERIOD):
        envelope[int(beat * ENVELOPE_RATE)] += 4.0
    return envelope.astype(np.float32)


class TestBeatGrid:
    def test_nearest_lands_on_a_beat_at_fraction_zero(self):
        grid = BeatGrid(period=1.5, phase=0.4, strength=1.0)

        assert grid.nearest(3.3, fraction=0.0) == pytest.approx(3.4)

    def test_nearest_lands_halfway_at_fraction_half(self):
        grid = BeatGrid(period=1.5, phase=0.4, strength=1.0)

        assert grid.nearest(3.3, fraction=0.5) == pytest.approx(2.65)

    def test_never_moves_more_than_half_a_period(self):
        grid = BeatGrid(period=1.5, phase=0.0, strength=1.0)

        for time in np.arange(0, 10, 0.07):
            assert abs(grid.nearest(float(time), 0.5) - time) <= PERIOD / 2 + 1e-6


class TestEstimateGrid:
    def test_finds_the_drum_period(self, drum_envelope):
        grid = estimate_grid(drum_envelope, centre=60.0)

        assert grid is not None
        assert grid.period == pytest.approx(PERIOD, abs=0.05)

    def test_finds_the_phase(self, drum_envelope):
        grid = estimate_grid(drum_envelope, centre=60.0)

        assert grid is not None
        assert (grid.phase - 0.4) % PERIOD == pytest.approx(0.0, abs=0.05)

    def test_reports_a_strong_grid_as_strong(self, drum_envelope):
        grid = estimate_grid(drum_envelope, centre=60.0)

        assert grid is not None
        assert grid.strength > 0.3

    def test_silence_gives_no_grid(self):
        assert estimate_grid(np.zeros(6000, dtype=np.float32), centre=30.0) is None

    def test_too_short_a_window_gives_no_grid(self):
        assert estimate_grid(np.ones(50, dtype=np.float32), centre=0.2) is None


class TestSnap:
    def test_a_boundary_moves_onto_the_grid(self, drum_envelope):
        spec = DecodeSpec(snap_fraction=0.5)

        moved, shift = snap_time(60.0, drum_envelope, spec)

        assert shift is not None
        assert abs(moved - 60.0) <= PERIOD / 2

    def test_snapping_at_zero_lands_on_a_beat(self, drum_envelope):
        moved, _ = snap_time(60.0, drum_envelope, DecodeSpec(snap_fraction=0.0))

        assert (moved - 0.4) % PERIOD == pytest.approx(0.0, abs=0.06)

    def test_a_flat_envelope_leaves_the_boundary_alone(self):
        flat = np.zeros(12000, dtype=np.float32)

        moved, shift = snap_time(60.0, flat, DecodeSpec())

        assert moved == 60.0
        assert shift is None

    def test_segments_keep_their_order(self, drum_envelope):
        segments = [Segment(20.0, 40.0), Segment(60.0, 80.0)]

        snapped, _ = snap_segments(segments, drum_envelope, DecodeSpec())

        assert all(s.end > s.start for s in snapped)
        assert snapped[1].start > snapped[0].end

    def test_the_report_counts_what_moved(self, drum_envelope):
        segments = [Segment(20.0, 40.0)]

        _, report = snap_segments(segments, drum_envelope, DecodeSpec())

        assert report.moved + report.skipped == 2

    def test_a_high_strength_requirement_snaps_nothing(self, drum_envelope):
        segments = [Segment(20.0, 40.0)]

        snapped, report = snap_segments(
            segments, drum_envelope, DecodeSpec(snap_strength=0.99)
        )

        assert snapped == segments
        assert report.moved == 0


class TestEnvelopeCache:
    def test_round_trips(self, tmp_path):
        envelope = np.arange(100, dtype=np.float32)
        save_envelope(tmp_path, 5, envelope)

        assert load_envelope(tmp_path, 5) == pytest.approx(envelope)

    def test_missing_returns_none(self, tmp_path):
        assert load_envelope(tmp_path, 9) is None

    def test_leaves_no_partial_file(self, tmp_path):
        save_envelope(tmp_path, 5, np.zeros(10, dtype=np.float32))

        assert list(tmp_path.glob("*.partial.npy")) == []
