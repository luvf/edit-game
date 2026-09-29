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


# Joins cache keys into one fused input: ``ast_ms+dinov2``.
FUSION = "+"


@dataclass(frozen=True)
class Span:
    """Where one encoder's features sit inside a fused embedding."""

    encoder: str
    start: int
    end: int


@dataclass(frozen=True)
class FusedStore:
    """Several caches read side by side, on the grid of the first.

    Each encoder keeps its own cache at its own rate; fusing them costs no
    extra disk. Every other cache is resampled onto the first one's grid by
    taking, for each step, its nearest embedding in time — a picture every
    0.2 s held for two audio steps. The error is a tenth of a second, a fifth
    of what the labels are good to.
    """

    stores: tuple[EmbeddingStore, ...]
    keys: tuple[str, ...]

    @property
    def encoder(self) -> str:
        """Return the fused cache key."""
        return FUSION.join(self.keys)

    @property
    def rate(self) -> float:
        """Return the grid rate, the first cache's."""
        return self.stores[0].rate

    @property
    def hop(self) -> float:
        """Return the seconds between two consecutive steps."""
        return self.stores[0].hop

    @property
    def dim(self) -> int:
        """Return the width of the concatenated embedding."""
        return sum(store.dim for store in self.stores)

    @property
    def spans(self) -> tuple[Span, ...]:
        """Return where each cache's features sit in a fused embedding."""
        spans, start = [], 0
        for key, store in zip(self.keys, self.stores, strict=True):
            spans.append(Span(key, start, start + store.dim))
            start += store.dim
        return tuple(spans)

    def has(self, game_id: int) -> bool:
        """Tell whether every cache holds the game."""
        return all(store.has(game_id) for store in self.stores)

    def steps(self, game_id: int) -> int:
        """Return how many steps the game holds on the first cache's grid."""
        return self.stores[0].steps(game_id)

    def load(self, game_id: int) -> np.ndarray:
        """Return a game's fused embeddings over its whole length.

        Built through `window`, so a whole game and a training window see the
        exact same resampling, down to the zeros past the end of a cache.
        """
        return self.window(game_id, 0.0, self.steps(game_id) * self.hop)

    def window(self, game_id: int, start: float, duration: float) -> np.ndarray:
        """Return the fused embeddings covering ``[start, start + duration)``.

        Steps past the end of a cache are zero, as with a single store.
        """
        first = self.stores[0].window(game_id, start, duration)
        times = start + (np.arange(first.shape[0], dtype=np.float64) + 0.5) * self.hop
        parts = [first]
        for store in self.stores[1:]:
            array = store.load(game_id)
            index = np.rint(times * store.rate).astype(np.int64)
            inside = (index >= 0) & (index < array.shape[0])
            part = np.zeros((first.shape[0], store.dim), dtype=np.float32)
            if inside.any():
                part[inside] = array[index[inside]].astype(np.float32)
            parts.append(part)
        return np.concatenate(parts, axis=1)


def open_store(root: Path, key: str) -> EmbeddingStore | FusedStore | None:
    """Return the cache named by `key` under `root`, fused when it says so.

    Args:
        root: the features directory, holding one subdirectory per cache.
        key: a cache key, or several joined by `FUSION`.

    Returns:
        The store, or None when any of the caches has not been built.
    """
    keys = tuple(key.split(FUSION))
    stores = [EmbeddingStore.open(root / name) for name in keys]
    if any(store is None for store in stores):
        return None
    if len(keys) == 1:
        return stores[0]
    return FusedStore(tuple(store for store in stores if store is not None), keys)
