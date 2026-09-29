"""Tests for the smoothing and `inside`-edge evidence used when decoding."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.datasets.targets import CHANNEL_INDEX
from game_autoedit.eval.decode import (
    DecodeSpec,
    boundary_scores,
    edge_evidence,
    smooth,
)


def count_peaks(curve: np.ndarray) -> int:
    """Count local maxima."""
    return int(((curve[1:-1] > curve[:-2]) & (curve[1:-1] >= curve[2:])).sum())


@pytest.fixture()
def flickering_plateau():
    """A plateau buried in the kind of flicker the `inside` channel shows."""
    rng = np.random.default_rng(0)
    base = np.zeros(2000)
    base[600:1400] = 1.0
    return np.clip(base + rng.normal(0, 0.35, base.size), 0, 1)


class TestSmooth:
    def test_zero_sigma_is_a_no_op(self):
        curve = np.array([0.0, 1.0, 0.0])

        assert smooth(curve, 0.0) == pytest.approx(curve)

    def test_empty_curve_survives(self):
        assert smooth(np.array([]), 3.0).size == 0

    def test_gaussian_removes_far_more_peaks_than_a_boxcar(self, flickering_plateau):
        # A rectangular window can create maxima the original never had, and
        # the next thing the decoder does is pick peaks.
        gaussian = count_peaks(smooth(flickering_plateau, 10.0, "gaussian"))
        box = count_peaks(smooth(flickering_plateau, 10.0, "box"))

        assert gaussian < box / 5

    def test_wider_gaussian_never_adds_peaks(self, flickering_plateau):
        counts = [
            count_peaks(smooth(flickering_plateau, sigma, "gaussian"))
            for sigma in (2, 5, 10, 20, 40)
        ]

        assert counts == sorted(counts, reverse=True)

    def test_preserves_the_plateau_level(self, flickering_plateau):
        smoothed = smooth(flickering_plateau, 10.0)

        # Smoothing must not shift the level, only quiet the flicker around it.
        assert smoothed[900:1100].mean() == pytest.approx(
            flickering_plateau[900:1100].mean(), abs=0.02
        )
        assert smoothed[900:1100].std() < flickering_plateau[900:1100].std() / 5

    def test_keeps_the_length(self, flickering_plateau):
        assert smooth(flickering_plateau, 7.0).shape == flickering_plateau.shape


class TestEdgeEvidence:
    @pytest.fixture()
    def step(self):
        curve = np.zeros(400)
        curve[200:] = 1.0
        return curve

    def test_a_rising_step_is_found_where_it_rises(self, step):
        evidence = edge_evidence(step, 30, rising=True)

        assert abs(int(np.argmax(evidence)) - 200) <= 2

    def test_a_falling_step_gives_no_rising_evidence(self, step):
        assert edge_evidence(step, 30, rising=True).max() > 0.9
        assert edge_evidence(step, 30, rising=False).max() == pytest.approx(0.0)

    def test_a_falling_step_is_found(self, step):
        evidence = edge_evidence(1.0 - step, 30, rising=False)

        assert abs(int(np.argmax(evidence)) - 200) <= 2

    def test_a_flat_curve_gives_nothing(self):
        evidence = edge_evidence(np.full(200, 0.7), 20, rising=True)

        assert evidence.max() == pytest.approx(0.0, abs=1e-6)

    def test_stays_within_zero_and_one(self, step):
        evidence = edge_evidence(step, 30, rising=True)

        assert evidence.min() >= 0.0
        assert evidence.max() <= 1.0

    def test_empty_input_survives(self):
        assert edge_evidence(np.array([]), 10, rising=True).size == 0


class TestBoundaryScores:
    @pytest.fixture()
    def probabilities(self):
        steps = 600
        values = np.zeros((steps, 3), dtype=np.float32)
        values[300:, CHANNEL_INDEX["inside"]] = 1.0
        values[295:305, CHANNEL_INDEX["in"]] = 0.4
        return values

    @pytest.fixture()
    def times(self):
        return (np.arange(600) + 0.5) * 0.1

    def test_zero_weight_returns_the_raw_channels(self, probabilities, times):
        scores = boundary_scores(probabilities, times, DecodeSpec(inside_weight=0.0))

        assert scores["in"] == pytest.approx(probabilities[:, CHANNEL_INDEX["in"]])

    def test_weighting_lifts_a_boundary_the_inside_curve_agrees_with(
        self, probabilities, times
    ):
        raw = boundary_scores(probabilities, times, DecodeSpec(inside_weight=0.0))
        blended = boundary_scores(
            probabilities, times, DecodeSpec(inside_weight=0.5, evidence_span=3.0)
        )

        assert blended["in"].max() > raw["in"].max()

    def test_full_weight_ignores_the_boundary_channel(self, probabilities, times):
        scores = boundary_scores(probabilities, times, DecodeSpec(inside_weight=1.0))
        without = probabilities.copy()
        without[:, CHANNEL_INDEX["in"]] = 0.0
        same = boundary_scores(without, times, DecodeSpec(inside_weight=1.0))

        assert scores["in"] == pytest.approx(same["in"])

    def test_returns_both_boundary_channels(self, probabilities, times):
        scores = boundary_scores(probabilities, times, DecodeSpec(inside_weight=0.5))

        assert set(scores) == {"in", "out"}
