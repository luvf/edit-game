"""Tests for game_autoedit.eval.metrics."""

from __future__ import annotations

import pytest

from game_autoedit.data.labels import Segment
from game_autoedit.eval.metrics import Aggregate, match_boundaries, score_segments


class TestMatchBoundaries:
    def test_exact_match(self):
        score = match_boundaries([10.0, 20.0], [10.0, 20.0], channel="in")

        assert score.matched == 2
        assert score.f1 == 1.0

    def test_match_within_tolerance(self):
        score = match_boundaries([10.3], [10.0], channel="in", tolerance=0.5)

        assert score.matched == 1
        assert score.median_error == pytest.approx(0.3)

    def test_no_match_beyond_tolerance(self):
        score = match_boundaries([11.0], [10.0], channel="in", tolerance=0.5)

        assert score.matched == 0
        assert score.recall == 0.0

    def test_each_truth_absorbs_one_prediction(self):
        score = match_boundaries([10.0, 10.1], [10.0], channel="in", tolerance=0.5)

        assert score.matched == 1
        assert score.predicted == 2
        assert score.precision == 0.5

    def test_missing_predictions_lower_recall(self):
        score = match_boundaries([10.0], [10.0, 50.0], channel="in")

        assert score.recall == 0.5
        assert score.precision == 1.0

    def test_empty_prediction_is_scoreless(self):
        score = match_boundaries([], [10.0], channel="in")

        assert score.precision == 0.0
        assert score.f1 == 0.0

    def test_median_error_is_nan_without_matches(self):
        score = match_boundaries([], [], channel="in")

        assert score.median_error != score.median_error  # NaN


class TestScoreSegments:
    def test_identical_cut_scores_one(self):
        segments = [Segment(10, 40), Segment(60, 90)]
        score = score_segments(segments, segments, duration=120.0)

        assert score.iou == pytest.approx(1.0, abs=0.02)
        assert score.missed_points == 0
        assert score.extra_segments == 0

    def test_missing_segment_counts_as_a_missed_point(self):
        score = score_segments(
            [Segment(10, 40)], [Segment(10, 40), Segment(60, 90)], duration=120.0
        )

        assert score.missed_points == 1
        assert score.extra_segments == 0

    def test_invented_segment_counts_as_extra(self):
        score = score_segments(
            [Segment(10, 40), Segment(60, 90)], [Segment(10, 40)], duration=120.0
        )

        assert score.extra_segments == 1
        assert score.missed_points == 0

    def test_partial_overlap_below_ratio_is_missed(self):
        score = score_segments(
            [Segment(10, 15)], [Segment(10, 40)], duration=120.0, overlap_ratio=0.5
        )

        assert score.missed_points == 1

    def test_kept_time_is_reported(self):
        score = score_segments([Segment(10, 40)], [Segment(10, 70)], duration=120.0)

        assert score.kept_predicted == pytest.approx(30.0, abs=0.2)
        assert score.kept_expected == pytest.approx(60.0, abs=0.2)


class TestAggregate:
    def test_pools_boundary_scores_across_games(self):
        aggregate = Aggregate.empty(("in", "out"))
        aggregate.add_boundaries(match_boundaries([10.0], [10.0], channel="in"))
        aggregate.add_boundaries(match_boundaries([20.0], [50.0], channel="in"))

        pooled = aggregate.boundary_score("in")
        assert pooled.expected == 2
        assert pooled.matched == 1
        assert pooled.recall == 0.5

    def test_pools_segment_scores(self):
        aggregate = Aggregate.empty(("in", "out"))
        for _ in range(2):
            aggregate.add_segments(
                score_segments([Segment(10, 40)], [Segment(10, 40)], duration=60.0)
            )

        assert aggregate.games == 2
        assert aggregate.iou == pytest.approx(1.0, abs=0.02)

    def test_empty_aggregate_has_zero_iou(self):
        assert Aggregate.empty(("in",)).iou == 0.0


class TestMergedAndSplit:
    def test_one_prediction_swallowing_two_points_is_merged(self):
        score = score_segments(
            [Segment(10, 100)],
            [Segment(10, 40), Segment(60, 100)],
            duration=120.0,
        )

        assert score.merged_segments == 1
        assert score.missed_points == 0

    def test_a_clean_one_to_one_match_is_not_merged(self):
        segments = [Segment(10, 40), Segment(60, 100)]
        score = score_segments(segments, segments, duration=120.0)

        assert score.merged_segments == 0
        assert score.split_points == 0

    def test_a_point_cut_in_two_is_split(self):
        score = score_segments(
            [Segment(10, 24), Segment(26, 40)],
            [Segment(10, 40)],
            duration=120.0,
        )

        assert score.split_points == 1
        # The two halves together still cover the point, so nothing is missed.
        assert score.missed_points == 0

    def test_two_overlapping_predictions_on_one_point_are_split(self):
        score = score_segments(
            [Segment(10, 40), Segment(12, 42)],
            [Segment(10, 40)],
            duration=120.0,
        )

        assert score.split_points == 1

    def test_merged_segment_still_counts_its_kept_time(self):
        score = score_segments(
            [Segment(10, 100)],
            [Segment(10, 40), Segment(60, 100)],
            duration=120.0,
        )

        assert score.kept_predicted == pytest.approx(90.0, abs=0.2)


class TestIntervalScore:
    """The editor works in beats, so the score should count beats."""

    @pytest.fixture()
    def envelope(self):
        import numpy as np

        from game_autoedit.data.beats import ENVELOPE_RATE

        seconds = 120
        values = np.random.default_rng(0).normal(0.2, 0.05, seconds * ENVELOPE_RATE)
        for beat in np.arange(0.4, seconds, 1.5):
            values[int(beat * ENVELOPE_RATE)] += 4.0
        return values.astype("float32")

    def test_a_boundary_in_the_same_interval_scores(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        score = score_intervals([60.3], [60.0], envelope, channel="in")

        assert score.accuracy == 1.0

    def test_a_boundary_one_beat_away_does_not(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        score = score_intervals([61.5], [60.0], envelope, channel="in")

        assert score.accuracy == 0.0
        assert score.within_one == 1.0

    def test_sub_beat_error_either_side_counts_the_same(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        early = score_intervals([59.7], [60.0], envelope, channel="in")
        late = score_intervals([60.3], [60.0], envelope, channel="in")

        assert early.accuracy == late.accuracy

    def test_a_boundary_far_away_counts_as_unmatched(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        score = score_intervals([90.0], [60.0], envelope, channel="in")

        assert score.unmatched == 1
        assert score.accuracy == 0.0

    def test_no_prediction_at_all_counts_as_unmatched(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        score = score_intervals([], [60.0], envelope, channel="in")

        assert score.unmatched == 1

    def test_the_histogram_reports_the_offsets(self, envelope):
        from game_autoedit.eval.metrics import score_intervals

        score = score_intervals([60.1, 61.6], [60.0, 60.1], envelope, channel="in")

        assert sum(score.histogram().values()) == len(score.deltas)
