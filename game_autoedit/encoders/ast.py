"""The Audio Spectrogram Transformer as a frozen feature extractor.

AST is trained on AudioSet, whose label set includes Whistle, Cheering, Crowd
and Applause — exactly the events that separate a point from the dead time
around it. It has heard thousands of hours of them; 114 games never could.

Only the encoder is used: the classification head is dropped and the patch
tokens are pooled over frequency, leaving one 768-wide embedding every 0.1 s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch

from game_autoedit.config import SAMPLE_RATE

if TYPE_CHECKING:
    from game_autoedit.encoders.base import EncoderSpec

MODEL_NAME = "MIT/ast-finetuned-audioset-10-10-0.4593"

# AST's positional embeddings are fixed to this many mel frames at 100 Hz.
CHUNK_FRAMES = 1024
CHUNK_SECONDS = CHUNK_FRAMES / 100.0


class AstEncoder:
    """Frozen AST encoder producing one embedding per 0.1 s."""

    def __init__(self, spec: EncoderSpec, device: torch.device) -> None:
        """Load the pretrained weights and put them in eval mode."""
        from transformers import ASTModel, AutoFeatureExtractor

        self.spec = spec
        self.device = device
        self.features = AutoFeatureExtractor.from_pretrained(MODEL_NAME)  # type: ignore[no-untyped-call]
        model = ASTModel.from_pretrained(MODEL_NAME).eval().to(device)
        self.model = model.half() if spec.half and device.type == "cuda" else model
        self.dtype = next(self.model.parameters()).dtype

        config = self.model.config
        self._time_steps = (
            config.max_length - config.patch_size
        ) // config.time_stride + 1
        self._freq_steps = (
            config.num_mel_bins - config.patch_size
        ) // config.frequency_stride + 1
        self._dim = int(config.hidden_size)

    @property
    def rate(self) -> float:
        """Return the embedding rate: one token per time stride."""
        rate: float = self._time_steps / CHUNK_SECONDS
        return rate

    @property
    def dim(self) -> int:
        """Return the embedding width."""
        return self._dim

    def _chunks(self, waveform: np.ndarray) -> list[np.ndarray]:
        """Split a waveform into the fixed-length chunks AST expects."""
        size = int(CHUNK_SECONDS * SAMPLE_RATE)
        count = max(int(np.ceil(len(waveform) / size)), 1)
        padded = np.zeros(count * size, dtype=np.float32)
        padded[: len(waveform)] = waveform
        return [padded[index * size : (index + 1) * size] for index in range(count)]

    @torch.no_grad()
    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Return one embedding per 0.1 s for a whole waveform.

        Chunks are contiguous rather than overlapping: AST is a transformer over
        the full chunk, so every token already attends to all 10.24 s and the
        seam between chunks costs almost nothing — while the head downstream
        sees a minute of context either way.
        """
        chunks = self._chunks(waveform)
        outputs: list[np.ndarray] = []

        for start in range(0, len(chunks), self.spec.batch_size):
            batch = chunks[start : start + self.spec.batch_size]
            inputs = self.features(
                batch, sampling_rate=SAMPLE_RATE, return_tensors="pt"
            ).input_values.to(self.device, dtype=self.dtype)
            hidden = self.model(inputs).last_hidden_state[:, 2:, :]
            # Tokens are laid out frequency-major inside each time step.
            grid = hidden.reshape(
                hidden.shape[0], self._freq_steps, self._time_steps, self._dim
            )
            outputs.append(grid.mean(dim=1).float().cpu().numpy().astype(np.float16))

        stacked = np.concatenate(outputs, axis=0).reshape(-1, self._dim)
        wanted = int(np.floor(len(waveform) / SAMPLE_RATE * self.rate))
        return stacked[:wanted]
