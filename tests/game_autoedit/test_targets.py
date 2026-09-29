"""Tests for game_autoedit.datasets.targets."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.data.labels import GameLabels, Segment
from game_autoedit.datasets.targets import (
    CHANNEL_INDEX,
    TargetSpec,
    build_targets,
    positive_rates,
)


def labels(*segments):
    return GameLabels(
        game_id=1,
        fps=60.0,
        segments=[Segment(start, end) for start, end in segments],
        warnings=[],
    )


class TestBuildTargets:
    def test_shape_follows_duration_and_hop(self):
        spec = TargetSpec(hop=0.1)
        targets = build_targets(labels((10, 20)), duration=30.0, spec=spec)

        assert targets.shape == (300, 3)

    def test_in_channel_peaks_at_the_boundary(self):
        spec = TargetSpec(hop=0.1, tolerance=0.5, shape="gaussian")
        targets = build_targets(labels((10, 20)), duration=30.0, spec=spec)

        column = targets[:, CHANNEL_INDEX["in"]]
        assert np.argmax(column) == pytest.approx(100, abs=1)

    def test_rect_shape_is_flat_inside_the_tolerance(self):
        spec = TargetSpec(hop=0.1, tolerance=0.5, shape="rect")
        targets = build_targets(labels((10, 20)), duration=30.0, spec=spec)

        column = targets[:, CHANNEL_INDEX["in"]]
        assert set(np.unique(column)) == {0.0, 1.0}
        # A 1 s window at a 0.1 s hop covers ten steps.
        assert column.sum() == pytest.approx(10, abs=1)

    def test_tolerance_widens_the_positive_region(self):
        narrow = build_targets(
            labels((10, 20)),
            duration=30.0,
            spec=TargetSpec(hop=0.1, tolerance=0.25, shape="rect"),
        )
        wide = build_targets(
            labels((10, 20)),
            duration=30.0,
            spec=TargetSpec(hop=0.1, tolerance=1.0, shape="rect"),
        )

        index = CHANNEL_INDEX["in"]
        assert wide[:, index].sum() > narrow[:, index].sum()

    def test_inside_channel_covers_the_segment(self):
        spec = TargetSpec(hop=0.1)
        targets = build_targets(labels((10, 20)), duration=30.0, spec=spec)

        inside = targets[:, CHANNEL_INDEX["inside"]]
        assert inside[150] == 1.0
        assert inside[50] == 0.0

    def test_windowed_grid_shifts_the_boundary(self):
        spec = TargetSpec(hop=0.1, tolerance=0.5, shape="gaussian")
        targets = build_targets(labels((10, 20)), duration=5.0, spec=spec, start=8.0)

        column = targets[:, CHANNEL_INDEX["in"]]
        # The in at 10 s sits 2 s into a window starting at 8 s.
        assert np.argmax(column) == pytest.approx(20, abs=1)

    def test_out_channel_marks_the_segment_end(self):
        spec = TargetSpec(hop=0.1, tolerance=0.5, shape="gaussian")
        targets = build_targets(labels((10, 20)), duration=30.0, spec=spec)

        assert np.argmax(targets[:, CHANNEL_INDEX["out"]]) == pytest.approx(200, abs=1)

    def test_empty_labels_give_an_all_zero_target(self):
        targets = build_targets(labels(), duration=10.0, spec=TargetSpec(hop=0.1))

        assert targets.sum() == 0.0


class TestPositiveRates:
    def test_boundaries_are_far_rarer_than_inside(self):
        spec = TargetSpec(hop=0.1, tolerance=0.5, shape="rect")
        targets = build_targets(labels((10, 40)), duration=100.0, spec=spec)

        rates = positive_rates(targets)
        assert rates["inside"] > rates["in"] * 10

    def test_empty_input_returns_zeros(self):
        rates = positive_rates(np.zeros((0, 3), dtype=np.float32))

        assert set(rates.values()) == {0.0}
