"""From probability curves to a cut list.

The model answers per step; a cut file needs segments. Decoding is kept
separate from the model on purpose: the thresholds are the dial a human turns
when the tool proposes too much or too little, and turning it must not require
retraining.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

from game_autoedit.data.labels import Segment
from game_autoedit.datasets.targets import CHANNEL_INDEX

if TYPE_CHECKING:
    from collections.abc import Sequence

SmoothKernel = Literal["gaussian", "box"]


# Fallback for a channel with no configured trigger.
DEFAULT_THRESHOLD = 0.5


def smooth(
    curve: np.ndarray, sigma: float, kernel: SmoothKernel = "gaussian"
) -> np.ndarray:
    """Smooth a probability curve before its shape is read.

    The raw ``inside`` curve flickers: on a validation game it crosses the
    half-way mark thousands of times for a dozen real boundaries, so its edges
    are unusable as they stand.

    The default kernel is Gaussian rather than a moving average, and the reason
    matters here: a rectangular window can *create* local maxima that the
    original curve never had — its Fourier transform changes sign — and the
    next thing this pipeline does is pick peaks. The Gaussian is the only
    kernel that provably never introduces a new extremum as the smoothing
    widens, so every peak found afterwards corresponds to one that was really
    there. A boxcar is kept available to compare against.

    Args:
        curve: the per-step probabilities.
        sigma: smoothing width in steps; a boxcar reads it as its half-width.
        kernel: ``gaussian`` or ``box``.

    Returns:
        The smoothed curve, same length as the input.
    """
    if sigma <= 0 or curve.size == 0:
        return curve.astype(np.float64, copy=True)

    values = curve.astype(np.float64)
    if kernel == "box":
        width = max(int(round(2 * sigma)) | 1, 1)
        padding = width // 2
        padded = np.pad(values, padding, mode="edge")
        averaged = np.convolve(padded, np.ones(width) / width, mode="same")
        return averaged[padding : padding + len(values)]

    from scipy.ndimage import gaussian_filter1d

    smoothed: np.ndarray = gaussian_filter1d(values, sigma=sigma, mode="nearest")
    return smoothed


def edge_evidence(inside: np.ndarray, span: int, *, rising: bool) -> np.ndarray:
    """Return how strongly `inside` steps up or down around each instant.

    For every step, the mean of the `span` steps after it is compared with the
    mean of the `span` steps before. A point ending is exactly "we were inside
    and now we are not", so this reads the boundary off the channel that knows
    it best — and comparing two averages is far steadier than differentiating,
    which would only amplify the flicker.

    Args:
        inside: the ``inside`` probabilities, already smoothed.
        span: how many steps to average on each side.
        rising: True to detect a step up (a point starting), False for a step
            down (a point ending).

    Returns:
        Evidence in [0, 1], one value per step.
    """
    if inside.size == 0:
        return inside.astype(np.float32, copy=True)

    span = max(span, 1)
    padded = np.pad(inside.astype(np.float64), span, mode="edge")
    cumulative = np.concatenate([[0.0], np.cumsum(padded)])
    # Means of the `span` steps ending at, and starting from, each instant.
    before = (cumulative[span : span + len(inside)] - cumulative[: len(inside)]) / span
    after = (
        cumulative[2 * span : 2 * span + len(inside)]
        - cumulative[span : span + len(inside)]
    ) / span

    difference = (after - before) if rising else (before - after)
    evidence: np.ndarray = np.clip(difference, 0.0, 1.0).astype(np.float32)
    return evidence


@dataclass(frozen=True)
class DecodeSpec:
    """The thresholds and rules that turn curves into segments.

    Attributes:
        threshold: per-channel trigger level; a peak below it is not a
            candidate. Separate values because the two channels are not
            equally confident, and the two errors do not cost the same. A
            missed point has to be hunted for by scrubbing the game, while an
            extra segment is one delete — so `in` sits low enough to keep
            recall. `out` sits high because a premature end truncates a real
            point, which is the expensive failure dressed up as a cheap one.
            The defaults are the joint optimum measured on the validation
            games; retune them with a sweep after a run.
        min_peak_distance: seconds between two peaks of the same channel.
        min_gap: shortest dead time allowed between two kept segments. A game
            gives the teams time to reset between points, so a shorter gap
            means one point was cut in two rather than two points played back
            to back — the pair is merged. Only 1.8 % of real gaps fall between
            one and thirty seconds, and a further 5.3 % sit below a second,
            which are adjacent segments in the cut file rather than real play.
            Merging rather than dropping is deliberate: dropping could lose a
            real point, the expensive error.
        min_duration: shortest segment kept, in seconds.
        max_duration: longest segment kept; beyond this an ``out`` was missed.
        inside_veto: a candidate segment whose mean ``inside`` probability
            falls below this is dropped.
        inside_smoothing: smoothing width in seconds applied to ``inside``
            before its edges are read.
        smooth_kernel: ``gaussian``, which cannot invent a peak, or ``box``.
        inside_weight: how much of a boundary's score comes from the ``inside``
            edge rather than from the channel's own peak. 0 makes the strongest
            channel a mere veto, as it once was; 1 ignores the boundary
            channels entirely, which is worse than either — they do carry real
            information. The default is the measured optimum: past 0.35 the
            result collapses.
        evidence_span: seconds averaged either side of an instant when reading
            an ``inside`` edge.
    """

    threshold: dict[str, float] = field(
        default_factory=lambda: {"in": 0.50, "out": 0.70}
    )
    min_peak_distance: float = 3.0
    min_gap: float = 30.0
    min_duration: float = 4.0
    max_duration: float = 240.0
    inside_veto: float = 0.25
    inside_smoothing: float = 0.5
    smooth_kernel: SmoothKernel = "gaussian"
    inside_weight: float = 0.30
    evidence_span: float = 3.0


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


def boundary_scores(
    probabilities: np.ndarray, times: np.ndarray, spec: DecodeSpec
) -> dict[str, np.ndarray]:
    """Return the score each channel is peak-picked on.

    With `inside_weight` at zero this is just the raw channel. Above it, each
    boundary's score blends its own evidence with the step the ``inside``
    curve takes there — which is the point of having a channel that is right
    95 % of the time while the boundary channels are not.
    """
    weight = float(np.clip(spec.inside_weight, 0.0, 1.0))
    raw = {
        channel: probabilities[:, CHANNEL_INDEX[channel]].astype(np.float32)
        for channel in ("in", "out")
    }
    if weight == 0.0:
        return raw

    step = float(times[1] - times[0]) if len(times) > 1 else 1.0
    inside = smooth(
        probabilities[:, CHANNEL_INDEX["inside"]],
        spec.inside_smoothing / step,
        spec.smooth_kernel,
    )
    span = max(int(round(spec.evidence_span / step)), 1)
    evidence = {
        "in": edge_evidence(inside, span, rising=True),
        "out": edge_evidence(inside, span, rising=False),
    }
    return {
        channel: (1.0 - weight) * raw[channel] + weight * evidence[channel]
        for channel in raw
    }


def merge_close_segments(
    segments: list[Segment], min_gap: float, dropped: list[str]
) -> list[Segment]:
    """Merge segments separated by less than `min_gap` seconds."""
    merged: list[Segment] = []
    for segment in segments:
        if merged and segment.start - merged[-1].end < min_gap:
            previous = merged.pop()
            dropped.append(
                f"segments fusionnés autour de {previous.end:.1f}s : "
                f"{segment.start - previous.end:.1f}s d'écart, moins que les "
                f"{min_gap:.0f}s minimales entre deux points"
            )
            merged.append(Segment(previous.start, segment.end, previous.point))
            continue
        merged.append(segment)
    return merged


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
    inside = probabilities[:, CHANNEL_INDEX["inside"]]
    scores = boundary_scores(probabilities, times, spec)

    peaks: list[Peak] = []
    for channel in ("in", "out"):
        peaks.extend(
            Peak(time, score, channel)
            for time, score in find_peaks(
                scores[channel],
                times,
                threshold=spec.threshold.get(channel, DEFAULT_THRESHOLD),
                min_distance=spec.min_peak_distance,
            )
        )

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

    if spec.min_gap > 0:
        segments = merge_close_segments(segments, spec.min_gap, dropped)

    return Decoded(
        segments=segments, peaks=sorted(peaks, key=lambda p: p.time), dropped=dropped
    )
