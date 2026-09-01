"""From probability curves to a cut list.

The model answers per step; a cut file needs segments. Decoding is kept
separate from the model on purpose: the thresholds are the dial a human turns
when the tool proposes too much or too little, and turning it must not require
retraining.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from game_autoedit.data.labels import Segment
from game_autoedit.datasets.targets import CHANNEL_INDEX

if TYPE_CHECKING:
    from collections.abc import Sequence


# Fallback for a channel with no configured trigger.
DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class DecodeSpec:
    """The thresholds and rules that turn curves into segments.

    Attributes:
        threshold: per-channel trigger level; a peak below it is not a
            candidate. Separate values because the two channels are not
            equally confident: the `in` head puts almost all its true
            boundaries above 0.9, so a low trigger buys nothing but false
            positives, while the `out` head is far less sure and loses real
            boundaries above 0.7. The defaults are the joint optimum measured
            on the validation games; retune them with a sweep after a run.
        min_peak_distance: seconds between two peaks of the same channel.
        min_duration: shortest segment kept, in seconds.
        max_duration: longest segment kept; beyond this an ``out`` was missed.
        inside_veto: a candidate segment whose mean ``inside`` probability
            falls below this is dropped.
    """

    threshold: dict[str, float] = field(
        default_factory=lambda: {"in": 0.90, "out": 0.70}
    )
    min_peak_distance: float = 3.0
    min_duration: float = 4.0
    max_duration: float = 240.0
    inside_veto: float = 0.25


@dataclass(frozen=True)
class Peak:
    """One boundary candidate."""

    time: float
    score: float
    channel: str


@dataclass
class Decoded:
    """The decoding result, with everything a reviewer would want to see."""

    segments: list[Segment]
    peaks: list[Peak]
    dropped: list[str]


def find_peaks(
    curve: np.ndarray,
    times: np.ndarray,
    *,
    threshold: float,
    min_distance: float,
) -> list[tuple[float, float]]:
    """Return the local maxima of a curve above `threshold`.

    Peaks are taken strongest first and suppress their neighbours, so a broad
    bump yields one boundary rather than a cluster.

    Args:
        curve: per-step probabilities.
        times: the centre time of every step.
        threshold: minimum height of a peak.
        min_distance: seconds of suppression around a kept peak.

    Returns:
        ``(time, score)`` pairs, sorted by time.
    """
    if curve.size == 0:
        return []

    candidates = np.flatnonzero(curve >= threshold)
    if candidates.size == 0:
        return []

    order = candidates[np.argsort(-curve[candidates])]
    taken: list[int] = []
    for index in order:
        if all(abs(times[index] - times[other]) >= min_distance for other in taken):
            taken.append(int(index))

    return sorted((float(times[i]), float(curve[i])) for i in taken)


def _pair_peaks(peaks: Sequence[Peak], dropped: list[str]) -> list[tuple[Peak, Peak]]:
    """Pair ``in`` peaks with the ``out`` that closes them.

    Walks the timeline once. Two ``in`` in a row means the first was a false
    start, or the ``out`` between them was missed: the stronger one is kept and
    the other reported. An ``out`` with no open ``in`` is dropped.
    """
    pairs: list[tuple[Peak, Peak]] = []
    pending: Peak | None = None

    for peak in sorted(peaks, key=lambda item: item.time):
        if peak.channel == "in":
            if pending is not None:
                weaker = min(pending, peak, key=lambda item: item.score)
                pending = max(pending, peak, key=lambda item: item.score)
                dropped.append(
                    f"in isolé à {weaker.time:.1f}s (score {weaker.score:.2f}) : "
                    f"faux départ ou out manquant"
                )
            else:
                pending = peak
            continue

        if pending is None:
            dropped.append(f"out sans in à {peak.time:.1f}s (score {peak.score:.2f})")
            continue
        pairs.append((pending, peak))
        pending = None

    if pending is not None:
        dropped.append(f"in non refermé à {pending.time:.1f}s : out manquant en fin")
    return pairs


def decode(
    probabilities: np.ndarray,
    times: np.ndarray,
    spec: DecodeSpec,
) -> Decoded:
    """Turn per-step probabilities into a cut list.

    Args:
        probabilities: ``(steps, 3)`` in channel order.
        times: the centre time of every step.
        spec: thresholds and rules.

    Returns:
        The segments, the boundary candidates, and every rejection with a
        reason, so a reviewer can see what the model nearly proposed.
    """
    dropped: list[str] = []
    peaks: list[Peak] = []
    for channel in ("in", "out"):
        column = probabilities[:, CHANNEL_INDEX[channel]]
        peaks.extend(
            Peak(time, score, channel)
            for time, score in find_peaks(
                column,
                times,
                threshold=spec.threshold.get(channel, DEFAULT_THRESHOLD),
                min_distance=spec.min_peak_distance,
            )
        )

    inside = probabilities[:, CHANNEL_INDEX["inside"]]
    segments: list[Segment] = []
    for start_peak, end_peak in _pair_peaks(peaks, dropped):
        duration = end_peak.time - start_peak.time
        if duration < spec.min_duration:
            dropped.append(
                f"segment trop court à {start_peak.time:.1f}s ({duration:.1f}s)"
            )
            continue
        if duration > spec.max_duration:
            dropped.append(
                f"segment trop long à {start_peak.time:.1f}s ({duration:.1f}s)"
            )
            continue

        window = (times >= start_peak.time) & (times < end_peak.time)
        mean_inside = float(inside[window].mean()) if window.any() else 0.0
        if mean_inside < spec.inside_veto:
            dropped.append(
                f"segment rejeté à {start_peak.time:.1f}s : "
                f"probabilité 'dans un cut' {mean_inside:.2f}"
            )
            continue
        segments.append(Segment(start_peak.time, end_peak.time))

    return Decoded(
        segments=segments, peaks=sorted(peaks, key=lambda p: p.time), dropped=dropped
    )
