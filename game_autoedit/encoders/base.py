"""What every frozen encoder must offer.

An encoder turns a waveform into one embedding per instant on a regular grid.
It is never trained: its weights are frozen, its output is computed once per
game and cached, and only a small head is learned on top. With 114 games that
is the difference between a model that memorises them and one that generalises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np
    import torch


@dataclass(frozen=True)
class EncoderSpec:
    """Which encoder to use and how it was run.

    Attributes:
        name: registry key of the encoder.
        batch_size: chunks per forward pass when encoding a game.
        half: run in float16, which every supported encoder tolerates.
    """

    name: str = "ast"
    batch_size: int = 16
    half: bool = True

    @property
    def cache_key(self) -> str:
        """Return the subdirectory name this encoder's cache lives under."""
        return self.name


class FrozenEncoder(Protocol):
    """One embedding per instant, on a fixed grid."""

    @property
    def rate(self) -> float:
        """Return the number of embeddings produced per second."""
        ...

    @property
    def dim(self) -> int:
        """Return the embedding width."""
        ...

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Return ``(steps, dim)`` float16 embeddings for a whole waveform."""
        ...


def build_encoder(spec: EncoderSpec, device: torch.device) -> FrozenEncoder:
    """Instantiate the encoder named by `spec`.

    Raises:
        ValueError: on an unknown encoder name.
    """
    if spec.name == "ast":
        from game_autoedit.encoders.ast import AstEncoder

        return AstEncoder(spec, device)
    raise ValueError(f"encodeur inconnu : {spec.name}")
