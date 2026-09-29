"""Placing decoded boundaries on the drum grid.

The model answers on an 80 ms lattice, which lands a cut wherever a probability
peak happened to fall. A jugger game has a better lattice of its own: the drum,
every 1.50 s. Moving a boundary onto that grid removes the sub-beat jitter, and
aiming halfway between two beats keeps a clip from opening on a hit.

This runs after decoding, not inside it: the decoder works on probabilities
alone, and snapping needs the audio's onset envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from game_autoedit.data.beats import estimate_grid
from game_autoedit.data.labels import Segment

if TYPE_CHECKING:
    import numpy as np

    from game_autoedit.eval.decode import DecodeSpec


@dataclass(frozen=True)
class SnapReport:
    """What snapping did, so it can be shown and argued with."""

    moved: int
    skipped: int
    shifts: list[float]

    @property
    def median_shift(self) -> float:
        """Return the median absolute move, in seconds."""
        if not self.shifts:
            return 0.0
        ordered = sorted(abs(shift) for shift in self.shifts)
        return ordered[len(ordered) // 2]


def snap_time(
    time: float, envelope: np.ndarray, spec: DecodeSpec
) -> tuple[float, float | None]:
    """Move one instant onto the local drum grid.

    Returns:
        The chosen instant and how far it moved, or the original instant and
        None when no confident grid was found. The move is never more than half
        a period, so a boundary can never land in a different beat interval
        from the one the model chose.
    """
    grid = estimate_grid(envelope, centre=time, span=spec.snap_span)
    if grid is None or grid.strength < spec.snap_strength:
        return time, None

    target = grid.nearest(time, spec.snap_fraction)
    if abs(target - time) > grid.period / 2:
        return time, None
    return target, target - time


def snap_segments(
    segments: list[Segment], envelope: np.ndarray, spec: DecodeSpec
) -> tuple[list[Segment], SnapReport]:
    """Place the boundaries named by `spec.snap_channels` on the drum grid.

    Args:
        segments: the decoded segments.
        envelope: the game's onset strength.
        spec: carries the snapping thresholds.

    Returns:
        The moved segments and a report of what happened.
    """
    moved, skipped = 0, 0
    shifts: list[float] = []
    snapped: list[Segment] = []

    for segment in segments:
        start, start_shift = (
            snap_time(segment.start, envelope, spec)
            if "in" in spec.snap_channels
            else (segment.start, None)
        )
        end, end_shift = (
            snap_time(segment.end, envelope, spec)
            if "out" in spec.snap_channels
            else (segment.end, None)
        )
        for shift in (start_shift, end_shift):
            if shift is None:
                skipped += 1
                continue
            moved += 1
            shifts.append(shift)
        # A snap must never invert or empty a segment.
        if end <= start:
            snapped.append(segment)
            continue
        snapped.append(Segment(start, end, segment.point))

    return snapped, SnapReport(moved=moved, skipped=skipped, shifts=shifts)
