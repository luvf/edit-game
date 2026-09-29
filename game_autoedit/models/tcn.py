"""Temporal backbone and prediction heads.

A dilated convolution stack, because the decision at a given instant depends on
what happened over the previous ten or twenty seconds — a whistle is only an
``out`` if a point was running — and dilations buy that receptive field far more
cheaply than attention over 375 steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import torch.nn.functional as F  # noqa: N812
from torch import nn

from game_autoedit.datasets.targets import CHANNELS

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class BackboneSpec:
    """Shape of the temporal stack.

    Attributes:
        channels: width of the residual stack.
        downsample: strides applied before the stack; their product must match
            the ratio between the frontend rate and the output grid.
        dilations: one residual block per entry, doubling the receptive field.
        dropout: applied inside each residual block.
        stem_kernel: kernel of the strided convolutions.
    """

    channels: int = 256
    downsample: tuple[int, ...] = (2, 2, 2)
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)
    dropout: float = 0.1
    stem_kernel: int = 5

    @property
    def total_stride(self) -> int:
        """Return the overall temporal reduction of the stem."""
        stride = 1
        for factor in self.downsample:
            stride *= factor
        return stride

    def receptive_field(self, kernel: int = 3) -> int:
        """Return the stack's receptive field, in output steps."""
        return 1 + sum(2 * (kernel - 1) * dilation for dilation in self.dilations)


class ResidualBlock(nn.Module):
    """Two dilated convolutions with a residual connection."""

    def __init__(self, channels: int, dilation: int, dropout: float) -> None:
        """Build a block at the given dilation."""
        super().__init__()
        padding = dilation
        self.conv1 = nn.Conv1d(
            channels, channels, kernel_size=3, padding=padding, dilation=dilation
        )
        self.norm1 = nn.GroupNorm(8, channels)
        self.conv2 = nn.Conv1d(
            channels, channels, kernel_size=3, padding=padding, dilation=dilation
        )
        self.norm2 = nn.GroupNorm(8, channels)
        self.dropout = nn.Dropout(dropout)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Apply the block to ``(batch, channels, steps)``."""
        residual = features
        features = F.gelu(self.norm1(self.conv1(features)))
        features = self.dropout(features)
        features = self.norm2(self.conv2(features))
        return F.gelu(features + residual)


class CutTagger(nn.Module):
    """Predicts, for every step of the output grid, the three channel logits.

    The heads share the whole backbone: knowing a point is running is exactly
    what tells an ``out`` whistle from an ``in`` one, so the ``inside`` channel
    is not an auxiliary task bolted on the side but the context the boundary
    heads need.
    """

    def __init__(
        self,
        frontend: nn.Module,
        spec: BackboneSpec | None = None,
    ) -> None:
        """Assemble the frontend, the strided stem and the dilated stack."""
        super().__init__()
        self.frontend = frontend
        self.spec = spec or BackboneSpec()

        in_channels = int(frontend.out_channels)
        layers: list[nn.Module] = []
        for stride in self.spec.downsample:
            layers += [
                nn.Conv1d(
                    in_channels,
                    self.spec.channels,
                    kernel_size=self.spec.stem_kernel,
                    stride=stride,
                    padding=self.spec.stem_kernel // 2,
                ),
                nn.GroupNorm(8, self.spec.channels),
                nn.GELU(),
            ]
            in_channels = self.spec.channels
        self.stem = nn.Sequential(*layers)

        self.blocks = nn.Sequential(
            *[
                ResidualBlock(self.spec.channels, dilation, self.spec.dropout)
                for dilation in self.spec.dilations
            ]
        )
        self.head = nn.Conv1d(self.spec.channels, len(CHANNELS), kernel_size=1)

    def forward(self, waveform: torch.Tensor, steps: int | None = None) -> torch.Tensor:
        """Predict channel logits for a batch of waveforms.

        Args:
            waveform: ``(batch, samples)``.
            steps: expected number of output steps; the stack is resized to it
                so a rounding difference in the frontend never shifts the grid.

        Returns:
            ``(batch, steps, len(CHANNELS))`` logits.
        """
        features = self.frontend(waveform)
        features = self.stem(features)
        features = self.blocks(features)
        logits = self.head(features)

        if steps is not None and logits.shape[-1] != steps:
            logits = F.interpolate(
                logits, size=steps, mode="linear", align_corners=False
            )
        output: torch.Tensor = logits.transpose(1, 2)
        return output


@dataclass(frozen=True)
class ModelSpec:
    """A full model description, serialisable into a run directory."""

    backbone: BackboneSpec = field(default_factory=BackboneSpec)
    frontend: str = "logmel"


def build_model(spec: ModelSpec) -> CutTagger:
    """Instantiate the model described by `spec`.

    Raises:
        ValueError: on an unknown frontend name.
    """
    if spec.frontend != "logmel":
        raise ValueError(f"frontend inconnu : {spec.frontend}")

    from game_autoedit.models.frontend import LogMelFrontend

    return CutTagger(LogMelFrontend(), spec.backbone)
