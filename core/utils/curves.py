"""Reading the model's probability curves, at the resolution asked for.

A game carries one probability per channel every 0.1 s — thirty thousand
values for fifty minutes. A timeline is two thousand pixels wide. Sending the
whole thing so the browser can throw away nine tenths of it costs a megabyte
and a half of JSON per cut opened, so the thinning happens here.

How it thins is the part that matters. A boundary peak is two or three steps
wide: averaging a bucket flattens it, and the curve would then fail to show
the very peak that produced a point. So `in` and `out` are reduced by their
maximum and `inside`, which is a plateau, by its mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

# The channels the model produces, and how each survives being thinned.
PEAK_CHANNELS = ("in", "out")
MEAN_CHANNELS = ("inside",)
CHANNELS = PEAK_CHANNELS + MEAN_CHANNELS

# Wide enough for any timeline, small enough to stay a ~30 KB response.
DEFAULT_POINTS = 1500
MAX_POINTS = 20000


class CurvesUnreadableError(RuntimeError):
    """The curves file is missing, truncated, or not what it claims to be."""


@dataclass(frozen=True)
class Curves:
    """The three curves, thinned to the resolution a caller asked for."""

    channels: dict[str, list[float]]
    hop: float
    duration: float
    steps: int

    def payload(self) -> dict[str, Any]:
        """Return the JSON body served to the front."""
        return {
            "hop": round(self.hop, 6),
            "duration": round(self.duration, 3),
            "points": len(next(iter(self.channels.values()), [])),
            "steps": self.steps,
            **self.channels,
        }


def _reduce(values: np.ndarray, points: int, *, peak: bool) -> np.ndarray:
    """Reduce `values` to `points` buckets, by maximum or by mean.

    The last bucket is short whenever the length is not a multiple, so the
    split is done with `array_split` rather than a reshape: no padding, no
    invented value at the end of the game.
    """
    if values.size <= points:
        return values
    buckets = np.array_split(values, points)
    reducer = np.max if peak else np.mean
    return np.array([reducer(bucket) for bucket in buckets], dtype=np.float32)


def load_curves(path: Path, *, points: int = DEFAULT_POINTS) -> Curves:
    """Read a curves file and thin it to `points` values per channel.

    Args:
        path: the ``.npz`` written next to the cut.
        points: how many values per channel to return. A file shorter than
            that is returned whole rather than stretched.

    Returns:
        The curves, with the hop and duration needed to place them in time.

    Raises:
        CurvesUnreadableError: the file cannot be read, or carries no channel.
    """
    resolution = max(1, min(int(points), MAX_POINTS))
    try:
        with np.load(path) as archive:
            stored = {name: archive[name] for name in archive.files}
    except (OSError, ValueError, EOFError) as error:
        raise CurvesUnreadableError(f"courbes illisibles : {error}") from error

    present = [name for name in CHANNELS if name in stored]
    if not present:
        raise CurvesUnreadableError(f"aucun canal connu dans {path.name}")

    times = stored.get("times")
    steps = int(stored[present[0]].shape[0])
    if times is not None and times.size > 1:
        hop = float(times[1] - times[0])
        duration = float(times[-1]) + hop / 2
    else:
        hop, duration = 0.0, 0.0

    channels = {
        name: [
            round(float(value), 3)
            for value in _reduce(
                np.asarray(stored[name], dtype=np.float32),
                resolution,
                peak=name in PEAK_CHANNELS,
            )
        ]
        for name in present
    }
    return Curves(channels=channels, hop=hop, duration=duration, steps=steps)
