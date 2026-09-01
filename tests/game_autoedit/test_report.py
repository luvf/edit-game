"""Tests for game_autoedit.eval.report."""

from __future__ import annotations

import pytest

from game_autoedit.data.labels import Segment
from game_autoedit.eval.decode import Decoded, DecodeSpec, Peak
from game_autoedit.eval.report import build_comment

LOOSE = {"in": 0.3, "out": 0.3}


def comment_for(segments, peaks=(), dropped=()):
    decoded = Decoded(
        segments=[Segment(start, end) for start, end in segments],
        peaks=list(peaks),
        dropped=list(dropped),
    )
    return build_comment(
        decoded,
        duration=1200.0,
        fps=59.94,
        decode_spec=DecodeSpec(threshold=LOOSE),
        model_info={"run": "test"},
    )


class TestBuildComment:
    def test_reports_kept_time_and_ratio(self):
        comment = comment_for([(0, 100), (200, 300)])

        assert comment["stats"]["kept"] == 200.0
        assert comment["stats"]["kept_ratio"] == pytest.approx(1 / 6, abs=1e-4)

    def test_summarises_segments_and_gaps(self):
        comment = comment_for([(0, 100), (200, 300), (400, 500)])

        assert comment["stats"]["segments"]["count"] == 3
        assert comment["stats"]["gaps"]["count"] == 2
        assert comment["stats"]["gaps"]["median"] == 100.0

    def test_flags_a_segment_far_longer_than_the_median(self):
        comment = comment_for([(0, 30), (100, 130), (200, 230), (300, 700)])

        kinds = [item["kind"] for item in comment["review"]]
        assert "segment_long" in kinds

    def test_flags_a_pause_far_longer_than_the_median(self):
        comment = comment_for([(0, 30), (60, 90), (120, 150), (900, 930)])

        kinds = [item["kind"] for item in comment["review"]]
        assert "pause_longue" in kinds

    def test_flags_a_boundary_close_to_its_threshold(self):
        comment = comment_for(
            [(0, 100)], peaks=[Peak(time=0.0, score=0.31, channel="in")]
        )

        kinds = [item["kind"] for item in comment["review"]]
        assert "in_incertain" in kinds

    def test_confident_boundary_is_not_flagged(self):
        comment = comment_for(
            [(0, 100)], peaks=[Peak(time=0.0, score=0.95, channel="in")]
        )

        assert comment["review"] == []

    def test_review_is_sorted_by_time(self):
        comment = comment_for(
            [(0, 30), (100, 130), (200, 230), (300, 700)],
            peaks=[
                Peak(time=500.0, score=0.31, channel="in"),
                Peak(time=10.0, score=0.31, channel="out"),
            ],
        )

        times = [item["at"] for item in comment["review"]]
        assert times == sorted(times)

    def test_carries_the_decode_settings(self):
        comment = comment_for([(0, 100)])

        assert comment["decode"]["threshold"] == LOOSE

    def test_carries_the_rejections(self):
        comment = comment_for([(0, 100)], dropped=["out sans in à 5.0s"])

        assert comment["rejected"] == ["out sans in à 5.0s"]

    def test_few_segments_are_not_flagged_as_outliers(self):
        comment = comment_for([(0, 10), (100, 600)])

        assert comment["review"] == []
