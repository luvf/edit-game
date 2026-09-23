"""DINOv2 as a frozen feature extractor over a game's pictures.

DINOv2 is trained without labels to describe images well enough that a small
head on top can do the rest, which is exactly the situation here. Its patch
tokens keep *where* things are, and that is what a point looks like from the
touchline: two teams lined up on their base lines, a run to the middle, a
scrum, the players walking back.

Each frame becomes the CLS token plus the mean patch token of three vertical
bands -- left, centre, right -- because the field runs across the picture: the
bands say which half the play is in, which is also what tells a point won on
the left from one won on the right.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch

from game_autoedit.data.video import prefetched, read_frames

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from game_autoedit.encoders.base import EncoderSpec

MODEL_NAME = "facebook/dinov2-base"

# Frames per second. A point's shape plays out over seconds; the head reads the
# motion from how consecutive embeddings change.
FRAME_RATE = 5.0

# The picture the model sees, 16:9 and a multiple of the 14 px patch: 32 x 18
# patches. Enough to see a player; the source resolution does not matter.
FRAME_WIDTH = 448
FRAME_HEIGHT = 252
PATCH = 14

# CLS, then left, centre and right bands of patch columns.
BANDS = 3

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class DinoV2Encoder:
    """Frozen DINOv2 producing one embedding per frame, `FRAME_RATE` a second."""

    def __init__(self, spec: EncoderSpec, device: torch.device) -> None:
        """Load the pretrained weights and put them in eval mode."""
        from transformers import Dinov2Model

        self.spec = spec
        self.device = device
        # SDPA's fused attention nearly doubles the throughput on the card at
        # hand (250 frames/s against 140), and the model is what bounds it.
        model = (
            Dinov2Model.from_pretrained(MODEL_NAME, attn_implementation="sdpa")
            .eval()
            .to(device)
        )
        self.model = model.half() if spec.half and device.type == "cuda" else model
        self.dtype = next(self.model.parameters()).dtype
        self._width = int(self.model.config.hidden_size)
        self._mean = torch.tensor(IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
        self._std = torch.tensor(IMAGENET_STD, device=device).view(1, 3, 1, 1)

    @property
    def rate(self) -> float:
        """Return the number of embeddings produced per second."""
        return FRAME_RATE

    @property
    def dim(self) -> int:
        """Return the embedding width: CLS plus one mean per band."""
        return self._width * (1 + BANDS)

    def encode_video(self, sources: Sequence[Path]) -> np.ndarray:
        """Return ``(frames, dim)`` float16 embeddings for a whole game.

        Args:
            sources: the video files, in timeline order.
        """
        outputs = [
            self._encode_batch(frames)
            for frames in prefetched(
                read_frames(
                    sources,
                    rate=FRAME_RATE,
                    width=FRAME_WIDTH,
                    height=FRAME_HEIGHT,
                    batch=self.spec.batch_size,
                )
            )
        ]
        if not outputs:
            return np.zeros((0, self.dim), dtype=np.float16)
        return np.concatenate(outputs, axis=0)

    @torch.no_grad()
    def _encode_batch(self, frames: np.ndarray) -> np.ndarray:
        """Encode ``(n, height, width, 3)`` uint8 frames."""
        # The frames are a read-only view of ffmpeg's output buffer.
        pixels = torch.from_numpy(frames.copy()).to(self.device).permute(0, 3, 1, 2)
        pixels = (pixels.float() / 255.0 - self._mean) / self._std
        hidden = self.model(pixel_values=pixels.to(self.dtype)).last_hidden_state

        rows, columns = FRAME_HEIGHT // PATCH, FRAME_WIDTH // PATCH
        cls = hidden[:, 0]
        grid = hidden[:, 1:].reshape(hidden.shape[0], rows, columns, self._width)
        bands = [
            band.mean(dim=(1, 2)) for band in torch.tensor_split(grid, BANDS, dim=2)
        ]
        stacked = torch.cat([cls, *bands], dim=1)
        embeddings: np.ndarray = stacked.float().cpu().numpy().astype(np.float16)
        return embeddings
