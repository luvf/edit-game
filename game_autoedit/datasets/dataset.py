"""The torch dataset assembling audio windows and their targets.

Samples carry raw waveform, not features: the feature frontend belongs to the
model, so a log-mel baseline and a pretrained audio encoder can be swapped
without rebuilding anything on disk.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from torch.utils.data import Dataset

from game_autoedit.config import SAMPLE_RATE
from game_autoedit.data.audio import audio_info, read_window
from game_autoedit.data.labels import load_labels
from game_autoedit.datasets.targets import TargetSpec, build_targets
from game_autoedit.datasets.windows import SamplingSpec, WindowSpec, sample_starts

# A soft target at or above this counts as a positive step when reporting rates.
POSITIVE_LEVEL = 0.5

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from game_autoedit.config import Paths
    from game_autoedit.data.catalog import LabeledGame
    from game_autoedit.data.labels import GameLabels


@dataclass(frozen=True)
class DatasetSpec:
    """Everything that decides what a training epoch looks like."""

    window: WindowSpec = field(default_factory=WindowSpec)
    sampling: SamplingSpec = field(default_factory=SamplingSpec)
    target: TargetSpec = field(default_factory=TargetSpec)
    sample_rate: int = SAMPLE_RATE

    def steps_per_window(self) -> int:
        """Return the number of output steps in one window."""
        return self.target.steps_for(self.window.duration)

    def samples_per_window(self) -> int:
        """Return the number of audio samples in one window."""
        return int(round(self.window.duration * self.sample_rate))


@dataclass
class PreparedGame:
    """A game with its cached audio and its label timeline resolved."""

    game: LabeledGame
    audio_path: Path
    duration: float
    labels: GameLabels


def prepare_games(
    games: Sequence[LabeledGame], paths: Paths
) -> tuple[list[PreparedGame], list[tuple[int, str]]]:
    """Resolve cached audio and labels for a list of games.

    Returns:
        The games ready for training, and the ones skipped with the reason.
    """
    prepared: list[PreparedGame] = []
    skipped: list[tuple[int, str]] = []

    for game in games:
        path = paths.audio_path(game.game_id)
        cached = audio_info(path)
        if cached is None:
            skipped.append((game.game_id, "audio absent du cache"))
            continue

        labels = load_labels(
            game.cut_json_path,
            game_id=game.game_id,
            fps=game.fps,
            duration=cached.duration,
        )
        if not labels.segments:
            skipped.append((game.game_id, "aucun segment exploitable"))
            continue

        prepared.append(
            PreparedGame(
                game=game,
                audio_path=path,
                duration=cached.duration,
                labels=labels,
            )
        )

    return prepared, skipped


class GameWindowDataset(Dataset[dict[str, Any]]):
    """Windows of game audio paired with their per-step targets.

    The window list is rebuilt at every epoch through `resample`, so a
    stochastic sampling strategy actually sees new material each time instead
    of the same draw over and over.
    """

    def __init__(
        self,
        games: Sequence[PreparedGame],
        spec: DatasetSpec,
        *,
        seed: int = 0,
    ) -> None:
        """Store the games and draw the first epoch's windows."""
        self.games = list(games)
        self.spec = spec
        self.seed = seed
        self._index: list[tuple[int, float]] = []
        self.resample(epoch=0)

    def resample(self, epoch: int) -> None:
        """Draw the windows for one epoch."""
        rng = random.Random((self.seed, epoch).__hash__())
        index: list[tuple[int, float]] = []
        for position, prepared in enumerate(self.games):
            starts = sample_starts(
                prepared.labels,
                duration=prepared.duration,
                window=self.spec.window,
                sampling=self.spec.sampling,
                rng=rng,
            )
            index.extend((position, start) for start in starts)
        self._index = index

    def __len__(self) -> int:
        """Return the number of windows in the current epoch."""
        return len(self._index)

    def __getitem__(self, item: int) -> dict[str, Any]:
        """Return one window: waveform, targets, and where it came from."""
        position, start = self._index[item]
        prepared = self.games[position]

        waveform = read_window(
            prepared.audio_path,
            start,
            self.spec.window.duration,
            sample_rate=self.spec.sample_rate,
        )
        targets = build_targets(
            prepared.labels,
            duration=self.spec.window.duration,
            spec=self.spec.target,
            start=start,
        )
        # A window running past the end of the game is zero-padded audio, and
        # must not be trained on as if it were real silence between points.
        valid = (
            self.spec.target.centers(start, len(targets)) < prepared.duration
        ).astype(np.float32)

        return {
            "waveform": torch.from_numpy(waveform),
            "target": torch.from_numpy(targets),
            "valid": torch.from_numpy(valid),
            "game_id": prepared.game.game_id,
            "start": float(start),
        }

    def target_rates(self, max_windows: int = 512) -> dict[str, float]:
        """Estimate the positive rate of each channel over the current epoch."""
        from game_autoedit.datasets.targets import CHANNELS

        sampled = self._index[:max_windows]
        if not sampled:
            return dict.fromkeys(CHANNELS, 0.0)

        totals = np.zeros(len(CHANNELS), dtype=np.float64)
        for position, start in sampled:
            prepared = self.games[position]
            targets = build_targets(
                prepared.labels,
                duration=self.spec.window.duration,
                spec=self.spec.target,
                start=start,
            )
            totals += (targets >= POSITIVE_LEVEL).mean(axis=0)
        rates = totals / len(sampled)
        return {name: float(rates[index]) for index, name in enumerate(CHANNELS)}
