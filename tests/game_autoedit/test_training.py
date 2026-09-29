"""Tests for game_autoedit.training."""

from __future__ import annotations

import math

import numpy as np
import pytest

from game_autoedit.training import (
    MAX_POS_WEIGHT,
    average_precision,
    pos_weights,
    selection_score,
)


class TestPosWeights:
    def test_rare_channel_gets_a_high_weight(self):
        weights = pos_weights({"in": 0.01, "out": 0.01, "inside": 0.5})

        assert weights[0] == pytest.approx(MAX_POS_WEIGHT)

    def test_common_channel_gets_a_low_weight(self):
        weights = pos_weights({"in": 0.01, "out": 0.01, "inside": 0.5})

        assert weights[2] == pytest.approx(1.0)

    def test_weight_is_capped(self):
        weights = pos_weights({"in": 1e-9, "out": 1e-9, "inside": 1e-9})

        assert all(weight <= MAX_POS_WEIGHT for weight in weights)

    def test_missing_channel_falls_back_to_the_cap(self):
        assert pos_weights({})[0] == pytest.approx(MAX_POS_WEIGHT)


class TestAveragePrecision:
    def test_perfect_ranking_scores_one(self):
        scores = np.array([0.9, 0.8, 0.2, 0.1])
        targets = np.array([1.0, 1.0, 0.0, 0.0])

        assert average_precision(scores, targets) == pytest.approx(1.0)

    def test_reversed_ranking_scores_low(self):
        scores = np.array([0.1, 0.2, 0.8, 0.9])
        targets = np.array([1.0, 1.0, 0.0, 0.0])

        assert average_precision(scores, targets) < 0.6

    def test_no_positive_gives_nan(self):
        result = average_precision(np.array([0.5, 0.4]), np.array([0.0, 0.0]))

        assert math.isnan(result)


class TestSelectionScore:
    def test_averages_the_boundary_channels_only(self):
        score = selection_score({"ap_in": 0.4, "ap_out": 0.2, "ap_inside": 0.9})

        assert score == pytest.approx(0.3)

    def test_ignores_a_nan_channel(self):
        score = selection_score({"ap_in": 0.4, "ap_out": math.nan})

        assert score == pytest.approx(0.4)

    def test_all_nan_is_the_worst_possible_score(self):
        assert selection_score({"ap_in": math.nan, "ap_out": math.nan}) == -math.inf

    def test_prefers_better_boundaries_over_a_lower_loss(self):
        early = {"ap_in": 0.20, "ap_out": 0.05, "val_loss": 0.36}
        late = {"ap_in": 0.38, "ap_out": 0.06, "val_loss": 0.58}

        assert selection_score(late) > selection_score(early)
