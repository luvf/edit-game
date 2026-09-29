"""Tests for core.utils.curves."""

from __future__ import annotations

import numpy as np
import pytest

from core.utils.curves import (
    CurvesUnreadableError,
    load_curves,
)


def _write(path, **channels):
    """Write a curves file the way the pipeline does."""
    np.savez_compressed(
        path, **{k: np.asarray(v, dtype=np.float32) for k, v in channels.items()}
    )
    return path


@pytest.fixture()
def curves_path(tmp_path):
    """A curves file with a lone spike on `in` and a plateau on `inside`."""
    steps = 1000
    peak = np.zeros(steps, dtype=np.float32)
    peak[7] = 0.93
    return _write(
        tmp_path / "curves.npz",
        **{
            "in": peak,
            "out": np.zeros(steps, dtype=np.float32),
            "inside": np.full(steps, 0.4, dtype=np.float32),
            "times": (np.arange(steps) + 0.5) * 0.1,
        },
    )


class TestThinning:
    def test_a_spike_survives_because_boundaries_reduce_by_maximum(self, curves_path):
        curves = load_curves(curves_path, points=10)

        # 1000 steps into 10 buckets: the spike at step 7 lands in the first,
        # and a mean would have divided it by a hundred.
        assert curves.channels["in"][0] == pytest.approx(0.93, abs=1e-3)

    def test_a_plateau_keeps_its_level_because_inside_reduces_by_mean(
        self, curves_path
    ):
        curves = load_curves(curves_path, points=10)

        assert curves.channels["inside"] == [pytest.approx(0.4, abs=1e-3)] * 10

    def test_asking_for_more_points_than_there_are_returns_them_all(self, curves_path):
        curves = load_curves(curves_path, points=5000)

        assert len(curves.channels["in"]) == 1000
        assert curves.steps == 1000

    def test_a_length_that_does_not_divide_evenly_invents_no_value(self, tmp_path):
        path = _write(tmp_path / "odd.npz", **{"in": np.ones(1001)})

        curves = load_curves(path, points=100)

        assert len(curves.channels["in"]) == 100
        assert all(value == 1.0 for value in curves.channels["in"])

    def test_the_resolution_is_capped(self, curves_path):
        curves = load_curves(curves_path, points=10**9)

        assert len(curves.channels["in"]) == 1000


class TestTiming:
    def test_hop_and_duration_come_from_the_time_axis(self, curves_path):
        curves = load_curves(curves_path, points=10)

        assert curves.hop == pytest.approx(0.1, abs=1e-4)
        assert curves.duration == pytest.approx(100.0, abs=0.05)

    def test_a_file_without_times_still_loads(self, tmp_path):
        path = _write(tmp_path / "notimes.npz", **{"in": np.ones(10)})

        curves = load_curves(path, points=5)

        assert curves.hop == 0.0
        assert len(curves.channels["in"]) == 5


class TestUnreadable:
    def test_a_missing_file_is_reported(self, tmp_path):
        with pytest.raises(CurvesUnreadableError):
            load_curves(tmp_path / "nope.npz")

    def test_a_file_carrying_no_known_channel_is_reported(self, tmp_path):
        path = _write(tmp_path / "empty.npz", other=np.ones(10))

        with pytest.raises(CurvesUnreadableError, match="aucun canal"):
            load_curves(path)

    def test_a_truncated_file_is_reported_rather_than_raised_raw(self, tmp_path):
        path = tmp_path / "truncated.npz"
        path.write_bytes(b"not a zip")

        with pytest.raises(CurvesUnreadableError):
            load_curves(path)
