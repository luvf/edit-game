"""Tests for game_autoedit.datasets.windows."""

from __future__ import annotations

import random

from game_autoedit.data.labels import GameLabels, Segment
from game_autoedit.datasets.windows import (
    SamplingSpec,
    WindowSpec,
    dense_starts,
    sample_starts,
)


def labels(*segments):
    return GameLabels(
        game_id=1,
        fps=60.0,
        segments=[Segment(start, end) for start, end in segments],
        warnings=[],
    )


class TestDenseStarts:
    def test_covers_the_end_of_the_game(self):
        window = WindowSpec(duration=30.0, overlap=0.5)
        starts = dense_starts(100.0, window)

        assert starts[0] == 0.0
        assert starts[-1] == 70.0

    def test_short_game_gives_one_window(self):
        assert dense_starts(10.0, WindowSpec(duration=30.0)) == [0.0]

    def test_overlap_controls_the_stride(self):
        window = WindowSpec(duration=30.0, overlap=0.0)
        starts = dense_starts(120.0, window)

        assert starts[1] - starts[0] == 30.0


class TestSampleStarts:
    def test_dense_strategy_ignores_the_budget(self):
        starts = sample_starts(
            labels((10, 40)),
            duration=100.0,
            window=WindowSpec(duration=30.0),
            sampling=SamplingSpec(strategy="dense", windows_per_game=2),
            rng=random.Random(0),
        )

        assert len(starts) == len(dense_starts(100.0, WindowSpec(duration=30.0)))

    def test_budget_scales_with_duration(self):
        sampling = SamplingSpec(strategy="uniform", density=2.0)

        assert sampling.budget(60.0) == 2
        assert sampling.budget(600.0) == 20

    def test_fixed_budget_wins_over_density(self):
        sampling = SamplingSpec(strategy="uniform", windows_per_game=7, density=99.0)

        assert sampling.budget(600.0) == 7

    def test_boundary_strategy_lands_near_boundaries(self):
        window = WindowSpec(duration=30.0)
        starts = sample_starts(
            labels((100, 140)),
            duration=600.0,
            window=window,
            sampling=SamplingSpec(
                strategy="boundary",
                positive_ratio=1.0,
                jitter=0.0,
                windows_per_game=20,
            ),
            rng=random.Random(0),
        )

        centres = [start + window.duration / 2 for start in starts]
        assert all(abs(centre - 100) < 1 or abs(centre - 140) < 1 for centre in centres)

    def test_windows_stay_inside_the_game(self):
        window = WindowSpec(duration=30.0)
        starts = sample_starts(
            labels((5, 20)),
            duration=60.0,
            window=window,
            sampling=SamplingSpec(
                strategy="boundary",
                positive_ratio=1.0,
                jitter=30.0,
                windows_per_game=50,
            ),
            rng=random.Random(1),
        )

        assert all(0.0 <= start <= 30.0 for start in starts)

    def test_positive_ratio_splits_the_budget(self):
        starts = sample_starts(
            labels((100, 140)),
            duration=600.0,
            window=WindowSpec(duration=30.0),
            sampling=SamplingSpec(
                strategy="boundary",
                positive_ratio=0.5,
                jitter=0.0,
                windows_per_game=20,
            ),
            rng=random.Random(0),
        )

        anchored = sum(
            1
            for start in starts
            if abs(start + 15 - 100) < 1 or abs(start + 15 - 140) < 1
        )
        assert anchored == 10

    def test_falls_back_to_uniform_without_boundaries(self):
        starts = sample_starts(
            labels(),
            duration=600.0,
            window=WindowSpec(duration=30.0),
            sampling=SamplingSpec(strategy="boundary", windows_per_game=5),
            rng=random.Random(0),
        )

        assert len(starts) == 5

    def test_same_seed_gives_the_same_draw(self):
        args = {
            "duration": 600.0,
            "window": WindowSpec(duration=30.0),
            "sampling": SamplingSpec(strategy="uniform", windows_per_game=10),
        }
        first = sample_starts(labels((100, 140)), rng=random.Random(3), **args)
        second = sample_starts(labels((100, 140)), rng=random.Random(3), **args)

        assert first == second
