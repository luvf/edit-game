"""Choosing which stretches of audio a training epoch actually sees.

Boundaries are rare: a game holds one every forty seconds or so, and a boundary
is only positive for a second around it. Drawing windows uniformly therefore
spends almost the whole epoch on silence between points. The sampling strategy
is the main knob on that, so the strategies live here side by side and are
selected by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import random

    from game_autoedit.data.labels import GameLabels

Strategy = Literal["uniform", "boundary", "dense"]


@dataclass(frozen=True)
class WindowSpec:
    """The shape of one training sample.

    Attributes:
        duration: seconds of audio per sample. Long enough to carry the context
            that tells a whistle apart from a shout, short enough to batch.
        overlap: fraction of overlap between consecutive dense windows.
    """

    duration: float = 30.0
    overlap: float = 0.5

    @property
    def stride(self) -> float:
        """Return the seconds between two consecutive dense windows."""
        return max(self.duration * (1.0 - self.overlap), self.duration / 16)


@dataclass(frozen=True)
class SamplingSpec:
    """How many windows to draw from a game, and where.

    Attributes:
        strategy: ``uniform`` draws anywhere, ``boundary`` anchors a share of
            the windows on a real in/out instant, ``dense`` walks the game from
            end to end and is what evaluation and inference use.
        positive_ratio: with ``boundary``, the share of windows anchored on a
            boundary; the rest are drawn uniformly and act as negatives.
        jitter: how far, in seconds, an anchored boundary may sit from the
            window centre. Without it the model learns "the answer is in the
            middle".
        windows_per_game: fixed budget per game; when None, it is derived from
            the game duration so long games contribute more.
        density: windows per minute of game, used when `windows_per_game` is
            None.
    """

    strategy: Strategy = "boundary"
    positive_ratio: float = 0.5
    jitter: float = 8.0
    windows_per_game: int | None = None
    density: float = 1.0

    def budget(self, duration: float) -> int:
        """Return how many windows to draw from a game of `duration` seconds."""
        if self.windows_per_game is not None:
            return max(self.windows_per_game, 1)
        return max(int(round(duration / 60.0 * self.density)), 1)


def dense_starts(duration: float, window: WindowSpec) -> list[float]:
    """Return window starts walking the whole game, with overlap.

    The last window is pulled back so the end of the game is covered even when
    the duration is not a multiple of the stride.
    """
    if duration <= window.duration:
        return [0.0]

    starts: list[float] = []
    position = 0.0
    while position + window.duration < duration:
        starts.append(position)
        position += window.stride
    starts.append(max(duration - window.duration, 0.0))
    return starts


def _clamp_start(anchor: float, duration: float, window: WindowSpec) -> float:
    """Return a window start centred on `anchor`, kept inside the game."""
    start = anchor - window.duration / 2.0
    return min(max(start, 0.0), max(duration - window.duration, 0.0))


def sample_starts(
    labels: GameLabels,
    *,
    duration: float,
    window: WindowSpec,
    sampling: SamplingSpec,
    rng: random.Random,
) -> list[float]:
    """Draw the window start times of one game for one epoch.

    Args:
        labels: the game's label timeline, used to find the boundaries.
        duration: the game duration in seconds.
        window: the sample shape.
        sampling: the strategy and its parameters.
        rng: the random source, seeded by the caller for reproducibility.

    Returns:
        Window start times, in seconds.
    """
    if sampling.strategy == "dense":
        return dense_starts(duration, window)

    span = max(duration - window.duration, 0.0)
    count = sampling.budget(duration)

    if sampling.strategy == "uniform":
        return [rng.uniform(0.0, span) for _ in range(count)]

    boundaries = labels.ins + labels.outs
    if not boundaries:
        return [rng.uniform(0.0, span) for _ in range(count)]

    n_positive = int(round(count * sampling.positive_ratio))
    starts = [
        _clamp_start(
            rng.choice(boundaries) + rng.uniform(-sampling.jitter, sampling.jitter),
            duration,
            window,
        )
        for _ in range(n_positive)
    ]
    starts.extend(rng.uniform(0.0, span) for _ in range(count - n_positive))
    rng.shuffle(starts)
    return starts
