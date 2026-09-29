"""Tests for learning which side of the picture wins a point."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pytest
import torch

from game_autoedit.data.catalog import is_human_cut
from game_autoedit.data.embeddings import Span
from game_autoedit.data.labels import GameLabels, Segment, has_sides, load_labels
from game_autoedit.eval.report import side_guesses
from game_autoedit.models.side import (
    SideClassifier,
    SideFit,
    WeightProfile,
    accuracy,
    mirrored,
    pooled_features,
    sides_for,
    sides_from_logits,
    step_features,
    step_logits,
)

if TYPE_CHECKING:
    from pathlib import Path

FPS = 10.0


def _write_cut(path: Path, points: list[dict]) -> Path:
    path.write_text(json.dumps({"points": points}))
    return path


@dataclass
class FakeFile:
    path: str


@dataclass
class FakeCut:
    type_cut: str
    json_file: FakeFile
    pk: int = 1


class TestHumanCut:
    def test_a_raw_proposal_is_not_training_material(self, tmp_path):
        cut = _write_cut(
            tmp_path / "c.json", [{"in": 0, "out": 50, "point": "nopoint"}]
        )

        assert not is_human_cut(FakeCut("ML", FakeFile(str(cut))))

    def test_a_proposal_someone_gave_sides_to_is(self, tmp_path):
        cut = _write_cut(
            tmp_path / "c.json",
            [
                {"in": 0, "out": 50, "point": "nopoint"},
                {"in": 60, "out": 90, "point": "left"},
            ],
        )

        assert is_human_cut(FakeCut("ML", FakeFile(str(cut))))

    def test_any_other_cut_is(self, tmp_path):
        cut = _write_cut(tmp_path / "c.json", [{"in": 0, "out": 50}])

        assert is_human_cut(FakeCut("MAN", FakeFile(str(cut))))

    def test_an_unreadable_file_has_no_sides(self, tmp_path):
        assert not has_sides(tmp_path / "missing.json")


class TestLabels:
    def test_a_merged_segment_keeps_the_side_of_its_end(self, tmp_path):
        cut = _write_cut(
            tmp_path / "c.json",
            [
                {"in": 0, "out": 50, "point": "nopoint"},
                {"in": 51, "out": 100, "point": "right"},
            ],
        )

        labels = load_labels(cut, game_id=1, fps=FPS)

        assert [s.point for s in labels.segments] == ["right"]
        assert labels.has_sides


def _labels(*segments: Segment) -> GameLabels:
    return GameLabels(game_id=1, fps=FPS, segments=list(segments), warnings=[])


SIDE_SPEC = WeightProfile(kind="flat", rate=1.0, spread=1.0, before=2.0, after=-1.0)


class TestWeightProfile:
    def test_a_window_ends_before_the_point_does(self):
        # The winner shows as the stone goes in, a beat before the cut.
        segments = [Segment(1.0, 5.0, "left")]

        assert SIDE_SPEC.window(segments, 0) == (3.0, 4.0)

    def test_a_point_shorter_than_the_window_keeps_the_whole_window(self):
        # Two labelled points of 303 are this short; bounding the window to
        # the point itself changed nothing measurable, so it does not.
        segments = [Segment(4.5, 5.0, "left")]

        assert SIDE_SPEC.window(segments, 0) == (3.0, 4.0)

    def test_a_window_never_reaches_into_the_previous_point(self):
        segments = [Segment(1.0, 5.0, "left"), Segment(5.2, 5.6, "right")]

        assert SIDE_SPEC.window(segments, 1)[0] == 5.0

    def test_a_window_stops_where_the_next_point_starts(self):
        # Only reachable on a cut whose points nearly touch.
        segments = [Segment(1.0, 5.0, "left"), Segment(4.2, 9.0, "right")]

        assert SIDE_SPEC.window(segments, 0) == (3.0, 4.0)

    def test_poisson_peaks_before_the_end_and_stops_at_it(self):
        profile = WeightProfile()  # poisson, rate 2.3
        offsets = np.linspace(-8.0, 1.0, 91)

        weights = profile.weights(offsets)

        # A Poisson of mean 2.3 peaks half a second earlier, and is zero at
        # the cut itself.
        peak = -offsets[int(np.argmax(weights))]
        assert peak == pytest.approx(1.8, abs=0.4)
        assert (weights * -offsets).sum() / weights.sum() == pytest.approx(2.3, abs=0.2)
        assert not weights[offsets >= 0].any()

    def test_a_flat_profile_counts_its_window_alike(self):
        weights = SIDE_SPEC.weights(np.array([-2.5, -1.5, -0.5, 0.5]))

        assert list(weights) == [0.0, 1.0, 0.0, 0.0]

    def test_an_unknown_profile_is_refused(self):
        with pytest.raises(ValueError, match="profil"):
            WeightProfile(kind="patate").weights(np.array([-1.0]))

    def test_a_profile_round_trips_through_a_cut(self):
        profile = WeightProfile(kind="gaussian", rate=3.0, spread=0.8)

        assert WeightProfile.from_json(profile.to_json()) == profile

    def test_a_cut_without_a_profile_gets_the_default(self):
        assert WeightProfile.from_json(None) == WeightProfile()


class TestStepFeatures:
    class Store:
        """A fused store whose second half is one image band triple."""

        rate = 1.0
        dim = 10
        encoder = "ast_ms+dinov2"

        def __init__(self, array):
            self.array = array
            self.spans = (
                Span("ast_ms", 0, 2),
                Span("dinov2", 2, 10),
            )

        def load(self, _game_id):
            return self.array

    def test_reads_the_left_band_against_the_right_one(self):
        # 2 sound dimensions, then CLS, left, centre, right of width 2.
        steps = np.zeros((4, 10), dtype=np.float32)
        steps[:, 4:6] = [[3.0, 3.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]  # left
        steps[:, 8:10] = 1.0  # right

        features = step_features(self.Store(steps), 1)

        assert features is not None
        # Raw asymmetry 2, 0, 0, 0; minus its average over the game, 0.5.
        assert features[:, 0] == pytest.approx([1.5, -0.5, -0.5, -0.5])

    def test_a_store_without_pictures_has_no_features(self):
        class Sound:
            rate = 1.0
            dim = 4
            encoder = "ast"

            def load(self, _game_id):
                return np.zeros((4, 4), dtype=np.float32)

        assert step_features(Sound(), 1) is None


class TestPooledFeatures:
    def test_averages_the_end_window_of_each_point(self):
        # One value a second, whose value is the second it describes; the
        # windows are 3-4 s and 7-8 s.
        embeddings = np.arange(10, dtype=np.float32).reshape(10, 1)
        segments = [Segment(1.0, 5.0, "left"), Segment(6.0, 9.0, "right")]

        pooled = pooled_features(embeddings, 1.0, segments, SIDE_SPEC)

        assert pooled[:, 0] == pytest.approx([3.0, 7.0])

    def test_a_point_outside_the_embeddings_is_zero(self):
        embeddings = np.ones((4, 3), dtype=np.float32)

        pooled = pooled_features(embeddings, 1.0, [Segment(20.0, 25.0)], SIDE_SPEC)

        assert not pooled.any()


class TestSideClassifier:
    def _data(self, count=64):
        rng = np.random.default_rng(0)
        targets = (rng.random(count) > 0.5).astype(np.float32)
        # One informative dimension, buried in noise.
        features = rng.normal(size=(count, 8)).astype(np.float32)
        features[:, 3] += 4.0 * targets
        return features, targets

    def test_learns_a_side_it_can_see(self):
        features, targets = self._data()
        model = SideClassifier(features.shape[1])
        model.fit(features, targets)

        assert accuracy(model.probabilities(features), targets) > 0.9

    def test_round_trips_through_a_file(self, tmp_path):
        features, targets = self._data()
        model = SideClassifier(features.shape[1])
        model.fit(features, targets)
        model.save(tmp_path / "side.pt")

        reloaded = SideClassifier.load(tmp_path / "side.pt")

        assert reloaded.probabilities(features) == pytest.approx(
            model.probabilities(features), abs=1e-6
        )

    def test_reports_the_side_and_its_confidence(self):
        store = TestStepFeatures.Store(
            np.random.default_rng(0).normal(size=(10, 10)).astype(np.float32)
        )
        model = SideClassifier(2, profile=SIDE_SPEC)
        segments = [Segment(1.0, 5.0), Segment(6.0, 9.0)]

        answers = sides_for(model, store, 1, segments)

        assert answers is not None
        assert len(answers) == 2
        assert all(side in ("left", "right") for side, _ in answers)
        assert all(0.5 <= confidence <= 1.0 for _, confidence in answers)

    def test_no_classifier_means_no_answer(self):
        assert sides_for(None, None, 1, [Segment(0.0, 1.0)]) is None


class TestSideGuesses:
    def test_guesses_stay_out_of_the_points(self):
        guesses = side_guesses([Segment(1.0, 2.0)], [("left", 0.75)], FPS)

        assert guesses == [{"in": 10, "out": 20, "point": "left", "confidence": 0.75}]


class TestMirrored:
    def test_a_mirror_is_a_change_of_sign(self):
        features = np.array([[1.0, -2.0], [0.5, 0.0]], dtype=np.float32)
        targets = np.array([1.0, 0.0], dtype=np.float32)

        doubled, answers = mirrored(features, targets)

        assert doubled == pytest.approx(np.concatenate([features, -features]))
        assert list(answers) == [1.0, 0.0, 0.0, 1.0]


class TestSideCurve:
    def _classifier(self, weight, bias):
        model = SideClassifier(2)
        with torch.no_grad():
            model.net.weight.copy_(torch.tensor([weight]))
            model.net.bias.copy_(torch.tensor([bias]))
        return model

    def test_a_linear_classifier_answers_through_its_curve(self):
        # The logit of an averaged window equals the averaged logit, so the
        # curve must give exactly what pooling the window gives.
        rng = np.random.default_rng(0)
        embeddings = rng.normal(size=(40, 2)).astype(np.float32)
        model = self._classifier([1.5, -0.5], 0.2)
        segments = [Segment(2.0, 10.0), Segment(12.0, 20.0)]
        times = np.arange(40, dtype=np.float64) + 0.5

        curve = step_logits(model, embeddings)
        from_curve = sides_from_logits(curve, times, segments, SIDE_SPEC)

        pooled = pooled_features(embeddings, 1.0, segments, SIDE_SPEC)
        direct = model.probabilities(pooled)
        assert from_curve is not None
        assert [c for _, c in from_curve] == pytest.approx(
            [max(p, 1 - p) for p in direct], abs=1e-5
        )

    def test_a_hidden_layer_has_no_curve(self):
        model = SideClassifier(2, SideFit(hidden=4))

        assert step_logits(model, np.zeros((5, 2), dtype=np.float32)) is None

    def test_no_curve_means_no_sides(self):
        assert sides_from_logits(np.array([]), np.array([]), [Segment(0, 1)]) is None


class TestPickCut:
    def _cut(self, tmp_path, type_cut, points, pk=1):
        path = _write_cut(tmp_path / f"{type_cut}_{pk}.json", points)
        return FakeCut(type_cut, FakeFile(str(path)), pk)

    def test_an_annotated_cut_comes_first_whatever_its_type(self, tmp_path):
        from game_autoedit.data.catalog import pick_cut

        edit = self._cut(tmp_path, "MAN", [{"in": 0, "out": 50}], pk=1)
        annotated = self._cut(
            tmp_path, "VID", [{"in": 0, "out": 50, "point": "right"}], pk=2
        )

        assert pick_cut([edit, annotated]) is annotated

    def test_a_reviewed_proposal_beats_a_reconstructed_cut(self, tmp_path):
        from game_autoedit.data.catalog import pick_cut

        raw = self._cut(tmp_path, "VID", [{"in": 0, "out": 50}], pk=1)
        reviewed = self._cut(
            tmp_path, "ML", [{"in": 0, "out": 50, "point": "left"}], pk=2
        )

        assert pick_cut([raw, reviewed]) is reviewed

    def test_a_raw_proposal_does_not(self, tmp_path):
        from game_autoedit.data.catalog import pick_cut

        raw_vid = self._cut(tmp_path, "VID", [{"in": 0, "out": 50}], pk=1)
        raw_ml = self._cut(
            tmp_path, "ML", [{"in": 0, "out": 50, "point": "nopoint"}], pk=2
        )

        assert pick_cut([raw_vid, raw_ml]) is raw_vid

    def test_a_real_edit_wins_among_cuts_nobody_annotated(self, tmp_path):
        from game_autoedit.data.catalog import pick_cut

        manual = self._cut(tmp_path, "MAN", [{"in": 0, "out": 50}], pk=1)
        rebuilt = self._cut(tmp_path, "VID", [{"in": 0, "out": 50}], pk=2)

        assert pick_cut([rebuilt, manual]) is manual

    def test_two_annotated_cuts_fall_back_on_the_type_order(self, tmp_path):
        from game_autoedit.data.catalog import pick_cut

        manual = self._cut(
            tmp_path, "MAN", [{"in": 0, "out": 50, "point": "left"}], pk=1
        )
        proposal = self._cut(
            tmp_path, "ML", [{"in": 0, "out": 50, "point": "left"}], pk=2
        )

        assert pick_cut([proposal, manual]) is manual
