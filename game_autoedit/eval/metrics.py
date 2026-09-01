"""Scoring a predicted cut against the edit a human actually made.

Two views, because they answer different questions. Boundary metrics say how
often the model finds the right instant, within the tolerance the labels
themselves are worth. Segment metrics say how much work is left to the person
who will review the result — the number that decides whether the tool is worth
opening.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from game_autoedit.data.labels import Segment

DEFAULT_TOLERANCE = 0.5


@dataclass(frozen=True)
class BoundaryScore:
    """How well one channel's boundaries were found."""

    channel: str
    matched: int
    predicted: int
    expected: int
    errors: list[float]

    @property
    def precision(self) -> float:
        """Return the share of predicted boundaries that were real."""
        return self.matched / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        """Return the share of real boundaries that were found."""
        return self.matched / self.expected if self.expected else 0.0

    @property
    def f1(self) -> float:
        """Return the harmonic mean of precision and recall."""
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    @property
    def median_error(self) -> float:
        """Return the median absolute timing error of the matched boundaries."""
        return float(np.median(self.errors)) if self.errors else float("nan")

    def line(self) -> str:
        """Return a one-line summary."""
        return (
            f"{self.channel:6s} P {self.precision:.3f}  R {self.recall:.3f}  "
            f"F1 {self.f1:.3f}  écart médian {self.median_error:.2f}s  "
            f"({self.matched}/{self.expected} trouvés, {self.predicted} proposés)"
        )


def match_boundaries(
    predicted: Sequence[float],
    expected: Sequence[float],
    *,
    channel: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> BoundaryScore:
    """Match predicted boundary instants to the true ones.

    Each true boundary can absorb at most one prediction, and each prediction
    takes the closest free true boundary within `tolerance`. Predictions are
    processed in time order, which makes the result independent of any score.

    Args:
        predicted: predicted instants, in seconds.
        expected: true instants, in seconds.
        channel: the channel being scored, for reporting.
        tolerance: how far a prediction may sit from the truth and still count.

    Returns:
        The counts and timing errors for this channel.
    """
    free = list(expected)
    used: set[int] = set()
    errors: list[float] = []

    for time in sorted(predicted):
        best_index, best_distance = -1, tolerance
        for index, truth in enumerate(free):
            if index in used:
                continue
            distance = abs(truth - time)
            if distance <= best_distance:
                best_index, best_distance = index, distance
        if best_index >= 0:
            used.add(best_index)
            errors.append(best_distance)

    return BoundaryScore(
        channel=channel,
        matched=len(errors),
        predicted=len(predicted),
        expected=len(expected),
        errors=errors,
    )


def _mask(segments: Sequence[Segment], times: np.ndarray) -> np.ndarray:
    """Return a boolean mask of the steps covered by `segments`."""
    mask = np.zeros(len(times), dtype=bool)
    for segment in segments:
        mask |= (times >= segment.start) & (times < segment.end)
    return mask


@dataclass(frozen=True)
class SegmentScore:
    """How much of the game the prediction agrees on, and what it costs to fix."""

    intersection: float
    union: float
    kept_predicted: float
    kept_expected: float
    missed_points: int
    extra_segments: int

    @property
    def iou(self) -> float:
        """Return the temporal intersection over union of the kept material."""
        return self.intersection / self.union if self.union else 0.0

    def line(self) -> str:
        """Return a one-line summary."""
        return (
            f"IoU {self.iou:.3f}  gardé {self.kept_predicted / 60:.1f} min "
            f"vs {self.kept_expected / 60:.1f} min attendues  "
            f"{self.missed_points} point(s) manqué(s), "
            f"{self.extra_segments} segment(s) en trop"
        )


def score_segments(
    predicted: Sequence[Segment],
    expected: Sequence[Segment],
    *,
    duration: float,
    step: float = 0.1,
    overlap_ratio: float = 0.5,
) -> SegmentScore:
    """Compare two cut lists over the whole game.

    Args:
        predicted: the proposed segments.
        expected: the segments a human kept.
        duration: the game duration, in seconds.
        step: resolution of the comparison grid.
        overlap_ratio: how much of a true segment must be covered for the point
            to count as found.

    Returns:
        Overlap of the kept material, and the review cost: points the reviewer
        would have to find by hand, and segments they would have to delete.
    """
    times = np.arange(0.0, duration, step)
    predicted_mask = _mask(predicted, times)
    expected_mask = _mask(expected, times)

    missed = 0
    for segment in expected:
        window = (times >= segment.start) & (times < segment.end)
        if not window.any():
            continue
        if predicted_mask[window].mean() < overlap_ratio:
            missed += 1

    extra = 0
    for segment in predicted:
        window = (times >= segment.start) & (times < segment.end)
        if not window.any():
            continue
        if expected_mask[window].mean() < overlap_ratio:
            extra += 1

    return SegmentScore(
        intersection=float((predicted_mask & expected_mask).sum()) * step,
        union=float((predicted_mask | expected_mask).sum()) * step,
        kept_predicted=float(predicted_mask.sum()) * step,
        kept_expected=float(expected_mask.sum()) * step,
        missed_points=missed,
        extra_segments=extra,
    )


@dataclass
class Aggregate:
    """Sums across games, so a per-game score can be pooled."""

    matched: dict[str, int]
    predicted: dict[str, int]
    expected: dict[str, int]
    errors: dict[str, list[float]]
    missed_points: int = 0
    extra_segments: int = 0
    intersection: float = 0.0
    union: float = 0.0
    games: int = 0

    @classmethod
    def empty(cls, channels: Sequence[str]) -> Aggregate:
        """Return a zeroed aggregate for the given channels."""
        return cls(
            matched=dict.fromkeys(channels, 0),
            predicted=dict.fromkeys(channels, 0),
            expected=dict.fromkeys(channels, 0),
            errors={channel: [] for channel in channels},
        )

    def add_boundaries(self, score: BoundaryScore) -> None:
        """Accumulate one game's boundary score."""
        self.matched[score.channel] += score.matched
        self.predicted[score.channel] += score.predicted
        self.expected[score.channel] += score.expected
        self.errors[score.channel].extend(score.errors)

    def add_segments(self, score: SegmentScore) -> None:
        """Accumulate one game's segment score."""
        self.missed_points += score.missed_points
        self.extra_segments += score.extra_segments
        self.intersection += score.intersection
        self.union += score.union
        self.games += 1

    def boundary_score(self, channel: str) -> BoundaryScore:
        """Return the pooled boundary score of one channel."""
        return BoundaryScore(
            channel=channel,
            matched=self.matched[channel],
            predicted=self.predicted[channel],
            expected=self.expected[channel],
            errors=self.errors[channel],
        )

    @property
    def iou(self) -> float:
        """Return the pooled temporal IoU."""
        return self.intersection / self.union if self.union else 0.0
