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
    from collections.abc import Sequence
    from pathlib import Path

    import numpy as np
    import torch

# Encoders that read a game's pictures rather than its sound.
VIDEO_ENCODERS: frozenset[str] = frozenset({"dinov2"})


@dataclass(frozen=True)
class EncoderSpec:
    """Which encoder to use and how it was run.

    Attributes:
        name: registry key of the encoder.
        batch_size: chunks per forward pass when encoding a game.
        half: run in float16, which every supported encoder tolerates.
        stereo: encode the mid and side channels separately and concatenate
            their embeddings, doubling the width. Side carries where a sound
            came from, which is what separates the match in front of the
            camera from the one behind it.
    """

    name: str = "ast"
    batch_size: int = 16
    half: bool = True
    stereo: bool = True

    @property
    def cache_key(self) -> str:
        """Return the subdirectory name this encoder's cache lives under.

        Mono and mid/side caches live side by side so a run on one can be
        compared against a run on the other. A picture has no channels.
        """
        if self.is_video:
            return self.name
        return f"{self.name}_ms" if self.stereo else self.name

    @property
    def is_video(self) -> bool:
        """Tell whether this encoder reads pictures instead of sound."""
        return self.name in VIDEO_ENCODERS


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
        """Return ``(steps, dim)`` float16 embeddings for a whole waveform.

        Args:
            waveform: ``(samples,)`` mono, or ``(samples, channels)`` when the
                encoder was built with `stereo`.
        """
        ...


class FrozenVideoEncoder(Protocol):
    """One embedding per frame, on a fixed grid starting at the first frame."""

    @property
    def rate(self) -> float:
        """Return the number of embeddings produced per second."""
        ...

    @property
    def dim(self) -> int:
        """Return the embedding width."""
        ...

    def encode_video(self, sources: Sequence[Path]) -> np.ndarray:
        """Return ``(frames, dim)`` float16 embeddings for a whole game."""
        ...


def build_encoder(
    spec: EncoderSpec, device: torch.device
) -> FrozenEncoder | FrozenVideoEncoder:
    """Instantiate the encoder named by `spec`.

    Raises:
        ValueError: on an unknown encoder name.
    """
    if spec.name == "ast":
        from game_autoedit.encoders.ast import AstEncoder

        return AstEncoder(spec, device)
    if spec.name == "dinov2":
        from game_autoedit.encoders.dinov2 import DinoV2Encoder

        return DinoV2Encoder(spec, device)
    raise ValueError(f"encodeur inconnu : {spec.name}")
