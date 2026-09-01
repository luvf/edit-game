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


def score_intervals(
    predicted: Sequence[float],
    expected: Sequence[float],
    envelope: np.ndarray,
    *,
    channel: str,
    strength: float = 0.15,
    span: float = 16.0,
    max_beats: int = 8,
) -> IntervalScore:
    """Score boundaries by the drum interval they land in.

    Both instants are measured on the same locally estimated grid, so an error
    in the grid's phase cancels out: what is compared is how many beats apart
    the two are, which is the question the editor actually cares about.

    Args:
        predicted: predicted instants, in seconds.
        expected: true instants, in seconds.
        envelope: the game's onset strength.
        channel: which channel is being scored, for reporting.
        strength: minimum periodicity before a grid is trusted.
        span: seconds of envelope used per estimate.
        max_beats: beyond this many beats a prediction is not the match for
            this boundary at all.

    Returns:
        The per-boundary beat offsets and how many found no prediction.
    """
    from game_autoedit.data.beats import estimate_grid

    deltas: list[int] = []
    unmatched = 0
    proposals = np.asarray(predicted, dtype=np.float64)

    for truth in expected:
        grid = estimate_grid(envelope, centre=truth, span=span)
        if grid is None or grid.strength < strength:
            continue
        if proposals.size == 0:
            unmatched += 1
            continue

        nearest = float(proposals[int(np.argmin(np.abs(proposals - truth)))])
        delta = round((nearest - truth) / grid.period)
        if abs(delta) > max_beats:
            unmatched += 1
            continue
        deltas.append(int(delta))

    return IntervalScore(channel=channel, deltas=deltas, unmatched=unmatched)


def _mask(segments: Sequence[Segment], times: np.ndarray) -> np.ndarray:
    """Return a boolean mask of the steps covered by `segments`."""
    mask = np.zeros(len(times), dtype=bool)
    for segment in segments:
        mask |= (times >= segment.start) & (times < segment.end)
    return mask


@dataclass(frozen=True)
class SegmentScore:
    """How much of the game the prediction agrees on, and what it costs to fix.

    The three failure counts are not interchangeable. A missed point has to be
    hunted for by scrubbing the game, so it is the expensive one. An extra
    segment is one delete. A merged segment — one prediction swallowing several
    real points — is expensive too: deleting it loses real material, and keeping
    it hides the boundary the model failed to find.
    """

    intersection: float
    union: float
    kept_predicted: float
    kept_expected: float
    missed_points: int
    extra_segments: int
    merged_segments: int = 0
    split_points: int = 0

    @property
    def iou(self) -> float:
        """Return the temporal intersection over union of the kept material."""
        return self.intersection / self.union if self.union else 0.0

    def line(self) -> str:
        """Return a one-line summary."""
        return (
            f"IoU {self.iou:.3f}  gardé {self.kept_predicted / 60:.1f} min "
            f"vs {self.kept_expected / 60:.1f} min attendues  "
            f"{self.missed_points} manqué(s), {self.extra_segments} en trop, "
            f"{self.merged_segments} fusionné(s), {self.split_points} coupé(s)"
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

    missed = sum(
        1
        for segment in expected
        if _covered_fraction(segment, predicted_mask, times) < overlap_ratio
    )
    extra = sum(
        1
        for segment in predicted
        if _covered_fraction(segment, expected_mask, times) < overlap_ratio
    )
    merged = sum(
        1
        for segment in predicted
        if _overlap_count(segment, expected, overlap_ratio) > 1
    )
    split = sum(
        1
        for segment in expected
        if _overlap_count(segment, predicted, overlap_ratio) > 1
    )

    return SegmentScore(
        intersection=float((predicted_mask & expected_mask).sum()) * step,
        union=float((predicted_mask | expected_mask).sum()) * step,
        kept_predicted=float(predicted_mask.sum()) * step,
        kept_expected=float(expected_mask.sum()) * step,
        missed_points=missed,
        extra_segments=extra,
        merged_segments=merged,
        split_points=split,
    )


def _covered_fraction(segment: Segment, mask: np.ndarray, times: np.ndarray) -> float:
    """Return how much of `segment` the mask covers, in [0, 1]."""
    window = (times >= segment.start) & (times < segment.end)
    return float(mask[window].mean()) if window.any() else 1.0


def _overlap_count(segment: Segment, others: Sequence[Segment], ratio: float) -> int:
    """Count how many of `others` have at least `ratio` of themselves inside."""
    total = 0
    for other in others:
        span = min(segment.end, other.end) - max(segment.start, other.start)
        if other.end > other.start and span / (other.end - other.start) >= ratio:
            total += 1
    return total


@dataclass(frozen=True)
class IntervalScore:
    """How often a boundary lands in the right drum interval.

    Seconds are the wrong unit for this problem. The game is beaten out every
    1.50 s, the editor places a cut in the middle of an interval, and the
    decoder puts it back there — so what actually matters is whether the model
    picked the right interval, not where inside it the boundary fell. Being
    0.4 s early and 0.4 s late are the same answer if both stay in the same
    beat; being 0.8 s out matters enormously if it crosses into the next one.
    """

    channel: str
    deltas: list[int]
    unmatched: int

    @property
    def total(self) -> int:
        """Return how many true boundaries were considered."""
        return len(self.deltas) + self.unmatched

    @property
    def exact(self) -> int:
        """Return how many landed in the right interval."""
        return sum(1 for delta in self.deltas if delta == 0)

    @property
    def accuracy(self) -> float:
        """Return the share of true boundaries placed in the right interval."""
        return self.exact / self.total if self.total else 0.0

    @property
    def within_one(self) -> float:
        """Return the share placed in the right interval or an adjacent one."""
        near = sum(1 for delta in self.deltas if abs(delta) <= 1)
        return near / self.total if self.total else 0.0

    def histogram(self) -> dict[int, int]:
        """Return how many boundaries fell each number of beats away."""
        counts: dict[int, int] = {}
        for delta in self.deltas:
            key = max(min(delta, 3), -3)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def line(self) -> str:
        """Return a one-line summary."""
        return (
            f"{self.channel:4s} bon intervalle {self.accuracy:.3f}  "
            f"à un intervalle près {self.within_one:.3f}  "
            f"({self.exact}/{self.total}, {self.unmatched} sans prédiction)"
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
    merged_segments: int = 0
    split_points: int = 0
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
        self.merged_segments += score.merged_segments
        self.split_points += score.split_points
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
