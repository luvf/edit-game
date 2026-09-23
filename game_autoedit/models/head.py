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

import torch
import torch.nn.functional as F  # noqa: N812
from torch import nn

from game_autoedit.datasets.targets import CHANNELS


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
        side_dropout: probability of zeroing the second half of the input for
            a whole window during training. With mid/side embeddings that half
            is the spatial channel, and five of the archived tournaments are
            dual mono where it is silence anyway. Without this the head would
            learn to depend on a cue that is simply absent on those, and do
            worse there than it does today.
        side_span: the ``[start, end)`` features `side_dropout` acts on. None
            is the second half of the input, which is where it sits when the
            input is a mid/side audio cache alone.
        video_span: the ``[start, end)`` features coming from pictures, when
            the input fuses sound and image.
        video_dropout: probability of zeroing `video_span` for a whole window
            during training, so the sound keeps its say and the head does not
            hand everything to the picture.
    """

    channels: int = 128
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128)
    dropout: float = 0.2
    input_dropout: float = 0.1
    side_dropout: float = 0.25
    side_span: tuple[int, int] | None = None
    video_span: tuple[int, int] | None = None
    video_dropout: float = 0.0

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
    """Predicts the three channel logits for every embedding step.

    Who won a point is *not* one of them: it is a separate classifier, for the
    reasons `game_autoedit.models.side` gives.
    """

    def __init__(self, input_dim: int, spec: HeadSpec | None = None) -> None:
        """Build the projection and the dilated stack."""
        super().__init__()
        self.spec = spec or HeadSpec()
        self.input_dim = input_dim

        self.input_dropout = nn.Dropout(self.spec.input_dropout)
        self.side_span = self.spec.side_span or (input_dim // 2, input_dim)
        self.project = nn.Conv1d(input_dim, self.spec.channels, kernel_size=1)
        self.project_norm = ChannelNorm(self.spec.channels)
        self.blocks = nn.Sequential(
            *[
                ResidualBlock(self.spec.channels, dilation, self.spec.dropout)
                for dilation in self.spec.dilations
            ]
        )
        self.head = nn.Conv1d(self.spec.channels, len(CHANNELS), kernel_size=1)

    def _drop_side(self, embeddings: torch.Tensor) -> torch.Tensor:
        """Zero the audio's spatial channel in some windows, in training only."""
        return self._drop_span(embeddings, self.side_span, self.spec.side_dropout)

    def _drop_span(
        self, embeddings: torch.Tensor, span: tuple[int, int] | None, rate: float
    ) -> torch.Tensor:
        """Zero `span` for a share `rate` of the windows, during training only."""
        if not self.training or rate <= 0 or span is None:
            return embeddings

        keep = torch.rand(embeddings.shape[0], 1, 1, device=embeddings.device) >= rate
        mask = torch.ones_like(embeddings)
        mask[:, :, span[0] : span[1]] = keep.to(embeddings.dtype)
        return embeddings * mask

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        """Predict channel logits for a batch of embedding sequences.

        Args:
            embeddings: ``(batch, steps, input_dim)``.

        Returns:
            ``(batch, steps, len(CHANNELS))`` logits, one per input step.
        """
        embeddings = self._drop_side(embeddings)
        embeddings = self._drop_span(
            embeddings, self.spec.video_span, self.spec.video_dropout
        )
        features = self.input_dropout(embeddings).transpose(1, 2)
        features = F.gelu(self.project_norm(self.project(features)))
        features = self.blocks(features)
        logits: torch.Tensor = self.head(features).transpose(1, 2)
        return logits
