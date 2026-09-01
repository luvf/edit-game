"""The trainable head over frozen embeddings.

This is the whole learned part of the two-stage model. The encoder already
knows what a whistle and a crowd sound like; the head only has to decide, given
a minute of that description around an instant, whether a point starts, ends,
or is running. It is deliberately small: with 114 games, capacity is the enemy.

It is fully convolutional, so the very same weights run on a 60 s training
window and on a two-hour game in one pass, with no windowing and no blending.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import torch.nn.functional as F  # noqa: N812
from torch import nn

from game_autoedit.datasets.targets import CHANNELS

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class HeadSpec:
    """Shape of the temporal head.

    Attributes:
        channels: width of the residual stack. Small on purpose.
        dilations: one residual block each; the receptive field doubles per
            entry, so eight blocks reach roughly two minutes at 10 Hz.
        dropout: applied inside each block and on the input projection.
        input_dropout: drops whole embedding dimensions, which stops the head
            from leaning on a handful of encoder features.
    """

    channels: int = 128
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128)
    dropout: float = 0.2
    input_dropout: float = 0.1

    def receptive_field(self, kernel: int = 3) -> int:
        """Return the receptive field, in embedding steps."""
        return 1 + sum(2 * (kernel - 1) * dilation for dilation in self.dilations)


class ChannelNorm(nn.Module):
    """Layer normalisation over the channels of each instant, alone.

    Normalising over time as well — which is what GroupNorm on a (B, C, T)
    tensor does — makes the statistics depend on the sequence length, so a head
    trained on one-minute windows would see a different distribution when run
    over a whole game. Normalising each instant independently keeps the network
    translation-equivariant, which is what lets the same weights run on any
    length and give the same answer.
    """

    def __init__(self, channels: int) -> None:
        """Build the norm for `channels` features."""
        super().__init__()
        self.norm = nn.LayerNorm(channels)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Normalise ``(batch, channels, steps)`` over the channel axis."""
        normalised: torch.Tensor = self.norm(features.transpose(1, 2)).transpose(1, 2)
        return normalised


class ResidualBlock(nn.Module):
    """Two dilated convolutions with a residual connection."""

    def __init__(self, channels: int, dilation: int, dropout: float) -> None:
        """Build a block at the given dilation."""
        super().__init__()
        self.conv1 = nn.Conv1d(
            channels, channels, kernel_size=3, padding=dilation, dilation=dilation
        )
        self.norm1 = ChannelNorm(channels)
        self.conv2 = nn.Conv1d(
            channels, channels, kernel_size=3, padding=dilation, dilation=dilation
        )
        self.norm2 = ChannelNorm(channels)
        self.dropout = nn.Dropout(dropout)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Apply the block to ``(batch, channels, steps)``."""
        residual = features
        features = F.gelu(self.norm1(self.conv1(features)))
        features = self.dropout(features)
        features = self.norm2(self.conv2(features))
        return F.gelu(features + residual)


class EmbeddingTagger(nn.Module):
    """Predicts the three channel logits for every embedding step."""

    def __init__(self, input_dim: int, spec: HeadSpec | None = None) -> None:
        """Build the projection and the dilated stack."""
        super().__init__()
        self.spec = spec or HeadSpec()
        self.input_dim = input_dim

        self.input_dropout = nn.Dropout(self.spec.input_dropout)
        self.project = nn.Conv1d(input_dim, self.spec.channels, kernel_size=1)
        self.project_norm = ChannelNorm(self.spec.channels)
        self.blocks = nn.Sequential(
            *[
                ResidualBlock(self.spec.channels, dilation, self.spec.dropout)
                for dilation in self.spec.dilations
            ]
        )
        self.head = nn.Conv1d(self.spec.channels, len(CHANNELS), kernel_size=1)

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        """Predict channel logits for a batch of embedding sequences.

        Args:
            embeddings: ``(batch, steps, input_dim)``.

        Returns:
            ``(batch, steps, len(CHANNELS))`` logits, one per input step.
        """
        features = self.input_dropout(embeddings).transpose(1, 2)
        features = F.gelu(self.project_norm(self.project(features)))
        features = self.blocks(features)
        logits: torch.Tensor = self.head(features).transpose(1, 2)
        return logits
