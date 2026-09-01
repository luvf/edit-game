"""The embedding cache.

Each game is encoded once by a frozen encoder and stored as a memory-mappable
array. Training then reads slices of it, which costs nothing: an epoch becomes
a matter of seconds instead of minutes, and the dataset-construction choices
that actually matter can be compared in an afternoon rather than a week.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

META = "meta.json"


@dataclass(frozen=True)
class EmbeddingStore:
    """One encoder's cache directory."""

    root: Path
    rate: float
    dim: int
    encoder: str

    @classmethod
    def open(cls, root: Path) -> EmbeddingStore | None:
        """Return the store at `root`, or None if it has not been built."""
        meta_path = root / META
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        return cls(
            root=root,
            rate=float(meta["rate"]),
            dim=int(meta["dim"]),
            encoder=str(meta["encoder"]),
        )

    @classmethod
    def create(
        cls, root: Path, *, rate: float, dim: int, encoder: str
    ) -> EmbeddingStore:
        """Create or update the store metadata at `root`."""
        root.mkdir(parents=True, exist_ok=True)
        (root / META).write_text(
            json.dumps({"rate": rate, "dim": dim, "encoder": encoder}, indent=2)
        )
        return cls(root=root, rate=rate, dim=dim, encoder=encoder)

    @property
    def hop(self) -> float:
        """Return the seconds between two consecutive embeddings."""
        return 1.0 / self.rate

    def path(self, game_id: int) -> Path:
        """Return the array path for a game."""
        return self.root / f"game_{game_id}.npy"

    def has(self, game_id: int) -> bool:
        """Tell whether a game has been encoded."""
        return self.path(game_id).exists()

    def write(self, game_id: int, embeddings: np.ndarray) -> None:
        """Store a game's embeddings, atomically."""
        target = self.path(game_id)
        tmp = target.with_suffix(".partial.npy")
        np.save(tmp, embeddings.astype(np.float16, copy=False))
        tmp.replace(target)

    def load(self, game_id: int) -> np.ndarray:
        """Return a memory-mapped view of a game's embeddings."""
        array: np.ndarray = np.load(self.path(game_id), mmap_mode="r")
        return array

    def steps(self, game_id: int) -> int:
        """Return how many embeddings a game holds, without reading them."""
        return int(self.load(game_id).shape[0])

    def window(self, game_id: int, start: float, duration: float) -> np.ndarray:
        """Return the embeddings covering ``[start, start + duration)``.

        Reads past the end are zero-padded, so a window near the last seconds
        of a game still comes back at the expected length.
        """
        wanted = int(round(duration * self.rate))
        offset = int(round(start * self.rate))
        array = self.load(game_id)

        first = max(offset, 0)
        last = min(offset + wanted, array.shape[0])
        out = np.zeros((wanted, array.shape[1]), dtype=np.float32)
        if last > first:
            out[first - offset : last - offset] = array[first:last].astype(np.float32)
        return out
