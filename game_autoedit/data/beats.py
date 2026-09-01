"""The drum grid.

A jugger game is timed by a drum, and it beats every 1.50 s — measured on the
archives, 94 % of run-ups, 92 % of dead time and 75 % of live play lock onto
that period, the last being lower only because the action covers it. The grid
therefore exists across the whole game, and a boundary can be placed on it
rather than wherever a probability peak happened to land.

The onset envelope is cached per game: computing it costs seconds and it is a
thousand times smaller than the audio, so every consumer can read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

# The envelope is sampled at this many points per second.
ENVELOPE_RATE = 100

# Where to look for the drum. Wide enough to catch a different cadence, narrow
# enough not to lock onto speech rhythm or a footstep pattern.
MIN_PERIOD = 1.0
MAX_PERIOD = 2.5

# Below this the window is silence and carries no rhythm to lock onto.
FLAT = 1e-6

# The drum's measured period, and how far a game may sit from it and still be
# counted as locked on when reporting.
DRUM_PERIOD = 1.5
DRUM_TOLERANCE = 0.1


@dataclass(frozen=True)
class BeatGrid:
    """A locally estimated drum grid.

    Attributes:
        period: seconds between two beats.
        phase: the time of one beat, in seconds on the game's timeline.
        strength: how periodic the envelope was, in [0, 1]. Below a threshold
            the grid is guesswork and nothing should be snapped to it.
    """

    period: float
    phase: float
    strength: float

    def nearest(self, time: float, fraction: float = 0.5) -> float:
        """Return the grid position closest to `time`.

        Args:
            time: the instant to place.
            fraction: where between two beats to aim. 0 lands on a beat, 0.5
                halfway between two — which is what a cut wants, since opening
                a clip on a drum hit sounds like a mistake.

        Returns:
            The chosen instant, in seconds.
        """
        offset = self.phase + fraction * self.period
        index = round((time - offset) / self.period)
        return offset + index * self.period


def onset_envelope(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Return the onset strength of a waveform at `ENVELOPE_RATE` Hz."""
    import librosa

    hop = max(sample_rate // ENVELOPE_RATE, 1)
    envelope: np.ndarray = librosa.onset.onset_strength(
        y=np.ascontiguousarray(audio), sr=sample_rate, hop_length=hop
    )
    return envelope.astype(np.float32)


def estimate_grid(
    envelope: np.ndarray,
    *,
    centre: float,
    span: float = 16.0,
    rate: int = ENVELOPE_RATE,
) -> BeatGrid | None:
    """Estimate the drum grid around one instant.

    Locally rather than once per game: the drum is struck by hand, so its phase
    drifts over half an hour even though its period does not.

    Args:
        envelope: the game's onset strength.
        centre: the instant to estimate around, in seconds.
        span: how many seconds of envelope to use.
        rate: the envelope's sample rate.

    Returns:
        The grid, or None when the envelope is too flat or too short to say.
    """
    half = int(span * rate / 2)
    middle = int(centre * rate)
    first = max(middle - half, 0)
    last = min(middle + half, len(envelope))
    window = envelope[first:last].astype(np.float64)

    if len(window) < int(2 * MAX_PERIOD * rate) or window.std() < FLAT:
        return None

    window = (window - window.mean()) / window.std()
    correlation = np.correlate(window, window, mode="full")[len(window) - 1 :]
    correlation /= correlation[0]

    low, high = int(MIN_PERIOD * rate), min(int(MAX_PERIOD * rate), len(correlation))
    if high <= low:
        return None
    lag = int(np.argmax(correlation[low:high])) + low
    period = lag / rate

    # Fold the envelope onto one period and take the fullest bin as the beat.
    positions = (np.arange(len(window)) % lag).astype(np.int64)
    folded = np.bincount(positions, weights=window, minlength=lag)
    phase = (first + int(np.argmax(folded))) / rate

    return BeatGrid(period=period, phase=phase, strength=float(correlation[lag]))


def envelope_path(root: Path, game_id: int) -> Path:
    """Return where a game's onset envelope is cached."""
    return root / f"game_{game_id}.npy"


def save_envelope(root: Path, game_id: int, envelope: np.ndarray) -> None:
    """Store a game's onset envelope, atomically."""
    root.mkdir(parents=True, exist_ok=True)
    target = envelope_path(root, game_id)
    tmp = target.with_suffix(".partial.npy")
    np.save(tmp, envelope.astype(np.float32, copy=False))
    tmp.replace(target)


def load_envelope(root: Path, game_id: int) -> np.ndarray | None:
    """Return a game's cached onset envelope, or None if it is not there."""
    path = envelope_path(root, game_id)
    if not path.exists():
        return None
    envelope: np.ndarray = np.load(path)
    return envelope
