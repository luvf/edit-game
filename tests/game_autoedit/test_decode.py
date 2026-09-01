"""Tests for game_autoedit.eval.decode."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.datasets.targets import CHANNEL_INDEX
from game_autoedit.eval.decode import DecodeSpec, decode, find_peaks

HOP = 0.1

# The logic tests pin their own triggers; the shipped defaults are tuned on real
# data and are pinned by a test of their own.
LOOSE = {"in": 0.3, "out": 0.3}


def grid(duration):
    steps = int(duration / HOP)
    return np.zeros((steps, 3), dtype=np.float32), (np.arange(steps) + 0.5) * HOP


def add_peak(curve, times, at, height=0.9, width=0.3):
    curve += height * np.exp(-0.5 * ((times - at) / width) ** 2)


def curves_for(segments, duration=200.0, inside=0.9):
    probabilities, times = grid(duration)
    for start, end in segments:
        add_peak(probabilities[:, CHANNEL_INDEX["in"]], times, start)
        add_peak(probabilities[:, CHANNEL_INDEX["out"]], times, end)
        window = (times >= start) & (times < end)
        probabilities[window, CHANNEL_INDEX["inside"]] = inside
    return probabilities, times


class TestFindPeaks:
    def test_finds_a_single_peak(self):
        _, times = grid(100.0)
        curve = np.zeros(len(times), dtype=np.float32)
        add_peak(curve, times, 50.0)

        peaks = find_peaks(curve, times, threshold=0.3, min_distance=3.0)

        assert len(peaks) == 1
        assert peaks[0][0] == pytest.approx(50.0, abs=0.2)

    def test_suppresses_neighbours_within_min_distance(self):
        _, times = grid(100.0)
        curve = np.zeros(len(times), dtype=np.float32)
        add_peak(curve, times, 50.0)
        add_peak(curve, times, 51.0, height=0.5)

        peaks = find_peaks(curve, times, threshold=0.3, min_distance=3.0)

        assert len(peaks) == 1

    def test_keeps_peaks_beyond_min_distance(self):
        _, times = grid(100.0)
        curve = np.zeros(len(times), dtype=np.float32)
        add_peak(curve, times, 20.0)
        add_peak(curve, times, 60.0)

        assert len(find_peaks(curve, times, threshold=0.3, min_distance=3.0)) == 2

    def test_threshold_filters_weak_peaks(self):
        _, times = grid(100.0)
        curve = np.zeros(len(times), dtype=np.float32)
        add_peak(curve, times, 50.0, height=0.2)

        assert find_peaks(curve, times, threshold=0.5, min_distance=3.0) == []

    def test_empty_curve_gives_no_peak(self):
        assert (
            find_peaks(np.zeros(0), np.zeros(0), threshold=0.3, min_distance=3.0) == []
        )


class TestDecode:
    def test_recovers_clean_segments(self):
        probabilities, times = curves_for([(20, 60), (100, 150)])

        decoded = decode(probabilities, times, DecodeSpec(threshold=LOOSE))

        assert len(decoded.segments) == 2
        assert decoded.segments[0].start == pytest.approx(20.0, abs=0.3)
        assert decoded.segments[1].end == pytest.approx(150.0, abs=0.3)

    def test_out_without_in_is_reported(self):
        probabilities, times = grid(100.0)
        add_peak(probabilities[:, CHANNEL_INDEX["out"]], times, 50.0)

        decoded = decode(probabilities, times, DecodeSpec(threshold=LOOSE))

        assert decoded.segments == []
        assert any("out sans in" in reason for reason in decoded.dropped)

    def test_unclosed_in_is_reported(self):
        probabilities, times = grid(100.0)
        add_peak(probabilities[:, CHANNEL_INDEX["in"]], times, 50.0)

        decoded = decode(probabilities, times, DecodeSpec(threshold=LOOSE))

        assert decoded.segments == []
        assert any("non refermé" in reason for reason in decoded.dropped)

    def test_two_ins_in_a_row_keep_the_stronger(self):
        probabilities, times = grid(200.0)
        add_peak(probabilities[:, CHANNEL_INDEX["in"]], times, 20.0, height=0.4)
        add_peak(probabilities[:, CHANNEL_INDEX["in"]], times, 60.0, height=0.9)
        add_peak(probabilities[:, CHANNEL_INDEX["out"]], times, 100.0)
        probabilities[(times >= 60) & (times < 100), CHANNEL_INDEX["inside"]] = 0.9

        decoded = decode(probabilities, times, DecodeSpec(threshold=LOOSE))

        assert len(decoded.segments) == 1
        assert decoded.segments[0].start == pytest.approx(60.0, abs=0.3)
        assert any("faux départ" in reason for reason in decoded.dropped)

    def test_short_segment_is_dropped(self):
        probabilities, times = curves_for([(20, 22)])

        decoded = decode(
            probabilities, times, DecodeSpec(threshold=LOOSE, min_duration=5.0)
        )

        assert decoded.segments == []
        assert any("trop court" in reason for reason in decoded.dropped)

    def test_long_segment_is_dropped(self):
        probabilities, times = curves_for([(10, 190)])

        decoded = decode(
            probabilities, times, DecodeSpec(threshold=LOOSE, max_duration=60.0)
        )

        assert decoded.segments == []
        assert any("trop long" in reason for reason in decoded.dropped)

    def test_inside_veto_rejects_a_dead_segment(self):
        probabilities, times = curves_for([(20, 60)], inside=0.05)

        decoded = decode(
            probabilities, times, DecodeSpec(threshold=LOOSE, inside_veto=0.25)
        )

        assert decoded.segments == []
        assert any("probabilité" in reason for reason in decoded.dropped)

    def test_threshold_is_per_channel(self):
        probabilities, times = curves_for([(20, 60)])
        probabilities[:, CHANNEL_INDEX["out"]] *= 0.3

        decoded = decode(
            probabilities, times, DecodeSpec(threshold={"in": 0.3, "out": 0.9})
        )

        assert decoded.segments == []

    def test_peaks_are_reported_in_time_order(self):
        probabilities, times = curves_for([(20, 60), (100, 150)])

        decoded = decode(probabilities, times, DecodeSpec(threshold=LOOSE))

        assert [peak.time for peak in decoded.peaks] == sorted(
            peak.time for peak in decoded.peaks
        )


class TestDefaultThresholds:
    def test_out_is_stricter_than_in(self):
        # A premature `out` truncates a real point, which costs more than an
        # extra segment; a strict `in` would simply lose points.
        spec = DecodeSpec()

        assert spec.threshold["out"] > spec.threshold["in"]

    def test_defaults_match_the_measured_optimum(self):
        spec = DecodeSpec()

        assert spec.threshold == {"in": 0.50, "out": 0.70}
