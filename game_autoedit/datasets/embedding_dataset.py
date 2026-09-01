"""Training material drawn from the embedding cache.

Same sampling strategies and same targets as the waveform dataset — only the
input changes. Reading a window is a slice of a memory-mapped array instead of
a decode, which is what makes comparing dataset-construction choices cheap.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from torch.utils.data import Dataset

from game_autoedit.data.labels import load_labels
from game_autoedit.datasets.dataset import POSITIVE_LEVEL
from game_autoedit.datasets.targets import CHANNELS, TargetSpec, build_targets
from game_autoedit.datasets.windows import SamplingSpec, WindowSpec, sample_starts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from game_autoedit.data.catalog import LabeledGame
    from game_autoedit.data.embeddings import EmbeddingStore
    from game_autoedit.data.labels import GameLabels


@dataclass(frozen=True)
class EmbeddingDatasetSpec:
    """What a training epoch looks like over embeddings.

    The target grid is the encoder's own grid: there is one prediction per
    embedding, so `hop` is not free — it comes from the store.
    """

    window: WindowSpec = field(default_factory=lambda: WindowSpec(duration=60.0))
    sampling: SamplingSpec = field(default_factory=SamplingSpec)
    target: TargetSpec = field(default_factory=TargetSpec)

    @classmethod
    def for_store(
        cls,
        store: EmbeddingStore,
        *,
        window: WindowSpec | None = None,
        sampling: SamplingSpec | None = None,
        tolerance: float = 0.5,
        shape: str = "gaussian",
    ) -> EmbeddingDatasetSpec:
        """Build a spec whose target grid matches the store's embedding grid."""
        return cls(
            window=window or WindowSpec(duration=60.0),
            sampling=sampling or SamplingSpec(),
            target=TargetSpec(hop=store.hop, tolerance=tolerance, shape=shape),  # type: ignore[arg-type]
        )

    def steps_per_window(self) -> int:
        """Return the number of embedding steps in one window.

        Derived from the target grid rather than computed independently, so a
        window and its targets can never end up one step apart.
        """
        return self.target.steps_for(self.window.duration)


@dataclass
class PreparedEmbeddingGame:
    """A game whose embeddings and labels are both resolved."""

    game: LabeledGame
    duration: float
    labels: GameLabels
    steps: int


def prepare_embedding_games(
    games: Sequence[LabeledGame], store: EmbeddingStore
) -> tuple[list[PreparedEmbeddingGame], list[tuple[int, str]]]:
    """Resolve embeddings and labels for a list of games.

    Returns:
        The games ready for training, and the ones skipped with the reason.
    """
    prepared: list[PreparedEmbeddingGame] = []
    skipped: list[tuple[int, str]] = []

    for game in games:
        if not store.has(game.game_id):
            skipped.append((game.game_id, "plongements absents du cache"))
            continue

        steps = store.steps(game.game_id)
        duration = steps / store.rate
        labels = load_labels(
            game.cut_json_path,
            game_id=game.game_id,
            fps=game.fps,
            duration=duration,
        )
        if not labels.segments:
            skipped.append((game.game_id, "aucun segment exploitable"))
            continue

        prepared.append(
            PreparedEmbeddingGame(
                game=game, duration=duration, labels=labels, steps=steps
            )
        )

    return prepared, skipped


class EmbeddingWindowDataset(Dataset[dict[str, Any]]):
    """Windows of cached embeddings paired with their per-step targets."""

    def __init__(
        self,
        games: Sequence[PreparedEmbeddingGame],
        store: EmbeddingStore,
        spec: EmbeddingDatasetSpec,
        *,
        seed: int = 0,
    ) -> None:
        """Store the games and draw the first epoch's windows."""
        self.games = list(games)
        self.store = store
        self.spec = spec
        self.seed = seed
        self._index: list[tuple[int, float]] = []
        self.resample(epoch=0)

    def resample(self, epoch: int) -> None:
        """Draw the windows for one epoch."""
        rng = random.Random((self.seed, epoch).__hash__())
        index: list[tuple[int, float]] = []
        for position, prepared in enumerate(self.games):
            index.extend(
                (position, start)
                for start in sample_starts(
                    prepared.labels,
                    duration=prepared.duration,
                    window=self.spec.window,
                    sampling=self.spec.sampling,
                    rng=rng,
                )
            )
        self._index = index

    def __len__(self) -> int:
        """Return the number of windows in the current epoch."""
        return len(self._index)

    def __getitem__(self, item: int) -> dict[str, Any]:
        """Return one window: embeddings, targets, and where it came from."""
        position, start = self._index[item]
        prepared = self.games[position]
        steps = self.spec.steps_per_window()

        embeddings = self.store.window(
            prepared.game.game_id, start, self.spec.window.duration
        )[:steps]
        targets = build_targets(
            prepared.labels,
            duration=self.spec.window.duration,
            spec=self.spec.target,
            start=start,
        )[:steps]
        valid = (
            self.spec.target.centers(start, len(targets)) < prepared.duration
        ).astype(np.float32)

        return {
            "embeddings": torch.from_numpy(embeddings),
            "target": torch.from_numpy(targets),
            "valid": torch.from_numpy(valid),
            "game_id": prepared.game.game_id,
            "start": float(start),
        }

    def target_rates(self, max_windows: int = 512) -> dict[str, float]:
        """Estimate the positive rate of each channel over the current epoch."""
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
