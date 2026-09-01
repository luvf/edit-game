"""Tests for game_autoedit.data.labels."""

from __future__ import annotations

import json

import pytest

from game_autoedit.data.labels import (
    MERGE_GAP_SECONDS,
    MIN_SEGMENT_SECONDS,
    has_points,
    load_labels,
)

FPS = 60000 / 1001


def write_cut(tmp_path, points, name="cut.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"points": points, "overlays": []}))
    return path


def frames(seconds):
    return int(round(seconds * FPS))


class TestLoadLabels:
    def test_converts_frames_to_seconds(self, tmp_path):
        path = write_cut(tmp_path, [{"in": frames(10), "out": frames(40)}])
        labels = load_labels(path, game_id=1, fps=FPS)

        assert len(labels.segments) == 1
        assert labels.segments[0].start == pytest.approx(10.0, abs=0.01)
        assert labels.segments[0].end == pytest.approx(40.0, abs=0.01)

    def test_sorts_out_of_order_points(self, tmp_path):
        path = write_cut(
            tmp_path,
            [
                {"in": frames(100), "out": frames(140)},
                {"in": frames(10), "out": frames(50)},
            ],
        )
        labels = load_labels(path, game_id=1, fps=FPS)

        assert labels.ins == sorted(labels.ins)

    def test_drops_inverted_segment(self, tmp_path):
        path = write_cut(tmp_path, [{"in": frames(40), "out": frames(10)}])
        labels = load_labels(path, game_id=1, fps=FPS)

        assert labels.segments == []
        assert any("inversé" in warning for warning in labels.warnings)

    def test_drops_overlapping_segment(self, tmp_path):
        path = write_cut(
            tmp_path,
            [
                {"in": frames(10), "out": frames(60)},
                {"in": frames(30), "out": frames(90)},
            ],
        )
        labels = load_labels(path, game_id=1, fps=FPS)

        assert len(labels.segments) == 1
        assert any("chevauchement" in warning for warning in labels.warnings)

    def test_merges_segments_closer_than_the_gap_threshold(self, tmp_path):
        gap = MERGE_GAP_SECONDS / 2
        path = write_cut(
            tmp_path,
            [
                {"in": frames(10), "out": frames(40)},
                {"in": frames(40 + gap), "out": frames(80)},
            ],
        )
        labels = load_labels(path, game_id=1, fps=FPS)

        assert len(labels.segments) == 1
        assert labels.segments[0].end == pytest.approx(80.0, abs=0.01)

    def test_drops_segments_shorter_than_the_minimum(self, tmp_path):
        short = MIN_SEGMENT_SECONDS / 2
        path = write_cut(tmp_path, [{"in": frames(10), "out": frames(10 + short)}])
        labels = load_labels(path, game_id=1, fps=FPS)

        assert labels.segments == []

    def test_clips_segment_running_past_the_media(self, tmp_path):
        path = write_cut(tmp_path, [{"in": frames(10), "out": frames(120)}])
        labels = load_labels(path, game_id=1, fps=FPS, duration=100.0)

        assert labels.segments[0].end == pytest.approx(100.0)
        assert any("tronqué" in warning for warning in labels.warnings)

    def test_drops_segment_starting_past_the_media(self, tmp_path):
        path = write_cut(tmp_path, [{"in": frames(200), "out": frames(240)}])
        labels = load_labels(path, game_id=1, fps=FPS, duration=100.0)

        assert labels.segments == []

    def test_ignores_malformed_point(self, tmp_path):
        path = write_cut(tmp_path, [{"in": "abc", "out": frames(40)}])
        labels = load_labels(path, game_id=1, fps=FPS)

        assert labels.segments == []
        assert any("illisible" in warning for warning in labels.warnings)

    def test_reports_gaps_and_kept_time(self, tmp_path):
        path = write_cut(
            tmp_path,
            [
                {"in": frames(10), "out": frames(40)},
                {"in": frames(100), "out": frames(130)},
            ],
        )
        labels = load_labels(path, game_id=1, fps=FPS)

        assert labels.kept_seconds == pytest.approx(60.0, abs=0.05)
        assert labels.gaps() == pytest.approx([60.0], abs=0.05)


class TestHasPoints:
    def test_true_for_a_real_cut(self, tmp_path):
        assert has_points(write_cut(tmp_path, [{"in": 0, "out": 60}])) is True

    def test_false_for_an_empty_cut(self, tmp_path):
        assert has_points(write_cut(tmp_path, [])) is False

    def test_false_for_a_missing_file(self, tmp_path):
        assert has_points(tmp_path / "nope.json") is False

    def test_false_for_invalid_json(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        assert has_points(path) is False
