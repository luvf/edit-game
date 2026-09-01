"""Label timelines turned into per-step training targets.

The model predicts three things on a regular time grid: the probability that a
step carries an ``in`` boundary, an ``out`` boundary, and the probability that
it sits inside a kept segment. Boundaries are instants, so a target that is
positive on a single step would be both unlearnable and pointless — the labels
themselves are only good to about half a second. They are therefore spread
over a tolerance window whose shape is a tunable choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from game_autoedit.data.labels import GameLabels

# Channel order used everywhere: targets, model outputs, curves.
CHANNELS: tuple[str, ...] = ("in", "out", "inside")
CHANNEL_INDEX = {name: index for index, name in enumerate(CHANNELS)}

TargetShape = Literal["rect", "triangle", "gaussian"]


@dataclass(frozen=True)
class TargetSpec:
    """How label timelines become per-step targets.

    Attributes:
        hop: seconds between two consecutive output steps.
        tolerance: half-width, in seconds, of the region around a boundary that
            counts as positive. Should match the label precision (~0.5 s) and
            the tolerance the evaluation uses.
        shape: how the positive region is weighted away from the exact instant.
        inside_margin: seconds trimmed from both ends of a kept segment before
            marking it as inside, so the ``inside`` channel does not fight the
            boundary channels right at the edges.
    """

    hop: float = 0.08
    tolerance: float = 0.5
    shape: TargetShape = "gaussian"
    inside_margin: float = 0.0

    def steps_for(self, duration: float) -> int:
        """Return the number of grid steps covering `duration` seconds."""
        return max(int(np.floor(duration / self.hop)), 0)

    def centers(self, start: float, steps: int) -> np.ndarray:
        """Return the centre time of each step of a grid starting at `start`."""
        return start + (np.arange(steps, dtype=np.float64) + 0.5) * self.hop


def _boundary_weights(
    centers: np.ndarray, boundaries: list[float], spec: TargetSpec
) -> np.ndarray:
    """Return the per-step weight induced by a list of boundary instants."""
    weights = np.zeros(len(centers), dtype=np.float32)
    if not boundaries:
        return weights

    for boundary in boundaries:
        distance = np.abs(centers - boundary)
        near = distance <= spec.tolerance
        if not near.any():
            continue
        if spec.shape == "rect":
            contribution = near.astype(np.float32)
        elif spec.shape == "triangle":
            contribution = np.clip(1.0 - distance / spec.tolerance, 0.0, 1.0)
        else:  # gaussian
            sigma = spec.tolerance / 2.0
            contribution = np.exp(-0.5 * (distance / sigma) ** 2)
            contribution[~near] = 0.0
        weights = np.maximum(weights, contribution.astype(np.float32))

    return weights


def _inside_mask(
    centers: np.ndarray, labels: GameLabels, spec: TargetSpec
) -> np.ndarray:
    """Return 1 for every step sitting inside a kept segment."""
    inside = np.zeros(len(centers), dtype=np.float32)
    for segment in labels.segments:
        start = segment.start + spec.inside_margin
        end = segment.end - spec.inside_margin
        if end <= start:
            continue
        inside[(centers >= start) & (centers < end)] = 1.0
    return inside


def build_targets(
    labels: GameLabels,
    *,
    duration: float,
    spec: TargetSpec,
    start: float = 0.0,
) -> np.ndarray:
    """Build the full target matrix of a game.

    Args:
        labels: the game's checked label timeline.
        duration: how many seconds of grid to produce.
        spec: how boundaries spread over the grid.
        start: time of the first step, for windowed grids.

    Returns:
        A ``(steps, 3)`` float32 array, channels ordered as `CHANNELS`.
    """
    steps = spec.steps_for(duration)
    centers = spec.centers(start, steps)
    return np.stack(
        [
            _boundary_weights(centers, labels.ins, spec),
            _boundary_weights(centers, labels.outs, spec),
            _inside_mask(centers, labels, spec),
        ],
        axis=-1,
    )


def positive_rates(targets: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    """Return the share of steps above `threshold` for each channel.

    Used to size the loss weighting: the boundary channels are two orders of
    magnitude rarer than ``inside``.
    """
    if targets.size == 0:
        return dict.fromkeys(CHANNELS, 0.0)
    above = (targets >= threshold).mean(axis=0)
    return {name: float(above[index]) for index, name in enumerate(CHANNELS)}
