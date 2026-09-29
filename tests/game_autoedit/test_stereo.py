"""Tests for the stereo handling that carries where a sound came from."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
import torch

from game_autoedit.data.audio import audio_info, mid_side, read_window
from game_autoedit.models.head import EmbeddingTagger, HeadSpec

RATE = 16000


@pytest.fixture()
def stereo_wav(tmp_path):
    """A file whose two channels differ, as a real archive's do."""
    path = tmp_path / "game_7.wav"
    left = np.linspace(-0.5, 0.5, RATE * 4, dtype=np.float32)
    right = left * 0.5
    sf.write(path, np.stack([left, right], axis=1), RATE, subtype="PCM_16")
    return path


class TestMidSide:
    def test_splits_a_stereo_signal(self):
        left = np.array([1.0, 0.0, -1.0], dtype=np.float32)
        right = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        mid, side = mid_side(np.stack([left, right], axis=1))

        assert mid == pytest.approx([0.5, 0.0, 0.0])
        assert side == pytest.approx([0.5, 0.0, -1.0])

    def test_dual_mono_has_a_silent_side(self):
        channel = np.array([0.3, -0.2, 0.7], dtype=np.float32)

        mid, side = mid_side(np.stack([channel, channel], axis=1))

        assert mid == pytest.approx(channel)
        assert side == pytest.approx(np.zeros(3))

    def test_mid_equals_the_mono_downmix(self):
        stereo = np.array([[1.0, 0.0], [0.0, 0.5]], dtype=np.float32)

        mid, _ = mid_side(stereo)

        assert mid == pytest.approx(stereo.mean(axis=1))

    def test_a_mono_input_survives(self):
        channel = np.array([0.1, 0.2], dtype=np.float32)

        mid, side = mid_side(channel)

        assert mid == pytest.approx(channel)
        assert side == pytest.approx(np.zeros(2))


class TestStereoCache:
    def test_the_cache_reports_two_channels(self, stereo_wav):
        info = audio_info(stereo_wav)

        assert info is not None
        assert info.channels == 2

    def test_reading_mono_downmixes(self, stereo_wav):
        window = read_window(stereo_wav, 0.0, 1.0, sample_rate=RATE)

        assert window.ndim == 1
        assert len(window) == RATE

    def test_reading_stereo_keeps_both_channels(self, stereo_wav):
        window = read_window(stereo_wav, 0.0, 1.0, sample_rate=RATE, mono=False)

        assert window.shape == (RATE, 2)
        assert not np.allclose(window[:, 0], window[:, 1])

    def test_padding_past_the_end_keeps_the_shape(self, stereo_wav):
        window = read_window(stereo_wav, 3.5, 2.0, sample_rate=RATE, mono=False)

        assert window.shape == (RATE * 2, 2)
        assert window[RATE:] == pytest.approx(np.zeros((RATE, 2)))


class TestSideDropout:
    """Five tournaments are dual mono: the head must not depend on side."""

    @pytest.fixture()
    def model(self):
        return EmbeddingTagger(64, HeadSpec(channels=16, dilations=(1,)))

    def test_side_is_sometimes_zeroed_while_training(self, model):
        model.train()
        torch.manual_seed(0)
        batch = torch.ones(200, 10, 64)

        dropped = (model._drop_side(batch)[:, :, 32:] == 0).all(dim=(1, 2))

        assert 0 < int(dropped.sum()) < 200

    def test_the_mid_half_is_never_touched(self, model):
        model.train()
        torch.manual_seed(0)
        batch = torch.ones(50, 10, 64)

        assert model._drop_side(batch)[:, :, :32] == pytest.approx(
            torch.ones(50, 10, 32).numpy()
        )

    def test_nothing_is_dropped_at_inference(self, model):
        model.eval()
        batch = torch.ones(50, 10, 64)

        assert torch.equal(model._drop_side(batch), batch)

    def test_a_zero_rate_disables_it(self):
        model = EmbeddingTagger(
            64, HeadSpec(channels=16, dilations=(1,), side_dropout=0.0)
        )
        model.train()
        batch = torch.ones(50, 10, 64)

        assert torch.equal(model._drop_side(batch), batch)

    def test_the_head_still_runs_on_doubled_width(self):
        model = EmbeddingTagger(1536, HeadSpec(channels=32, dilations=(1, 2)))

        assert model(torch.randn(2, 50, 1536)).shape == (2, 50, 3)
