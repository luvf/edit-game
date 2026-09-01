"""Waveform to features.

The frontend is a module of the model rather than a cached artefact on disk, so
swapping a log-mel baseline for a pretrained audio encoder changes one config
line and rebuilds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torchaudio
from torch import nn

from game_autoedit.config import SAMPLE_RATE


@dataclass(frozen=True)
class LogMelSpec:
    """Log-mel parameters.

    ``hop`` fixes the frontend rate at 100 Hz, which the backbone then reduces
    to the output grid. 64 bands up to 8 kHz keeps whistles, which sit around
    2-4 kHz, well resolved.
    """

    sample_rate: int = SAMPLE_RATE
    n_fft: int = 400
    hop_length: int = 160
    n_mels: int = 64
    f_min: float = 20.0
    f_max: float = 7800.0

    @property
    def rate(self) -> float:
        """Return the frontend frame rate in Hz."""
        return self.sample_rate / self.hop_length


class LogMelFrontend(nn.Module):
    """Log-mel spectrogram with per-window standardisation.

    Normalising each window by its own statistics costs nothing and removes the
    gain difference between tournaments, which is exactly the nuisance the
    held-out-tournament test is meant to expose.
    """

    def __init__(self, spec: LogMelSpec | None = None) -> None:
        """Build the mel filterbank described by `spec`."""
        super().__init__()
        self.spec = spec or LogMelSpec()
        self.mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=self.spec.sample_rate,
            n_fft=self.spec.n_fft,
            hop_length=self.spec.hop_length,
            n_mels=self.spec.n_mels,
            f_min=self.spec.f_min,
            f_max=self.spec.f_max,
            power=2.0,
            center=True,
        )

    @property
    def out_channels(self) -> int:
        """Return the number of feature channels produced."""
        return self.spec.n_mels

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        """Turn a batch of waveforms into normalised log-mel features.

        Args:
            waveform: ``(batch, samples)`` float32 in [-1, 1].

        Returns:
            ``(batch, n_mels, frames)`` float32.
        """
        features = torch.log(self.mel(waveform) + 1e-6)
        mean = features.mean(dim=(1, 2), keepdim=True)
        std = features.std(dim=(1, 2), keepdim=True).clamp_min(1e-5)
        return (features - mean) / std
