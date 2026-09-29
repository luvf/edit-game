"""Tests for fusing sound and picture caches, and for mirroring them."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.data.embeddings import EmbeddingStore, FusedStore, open_store

AUDIO_RATE = 10.0
VIDEO_RATE = 5.0


@pytest.fixture()
def features(tmp_path):
    audio = EmbeddingStore.create(
        tmp_path / "ast_ms", rate=AUDIO_RATE, dim=4, encoder="ast"
    )
    video = EmbeddingStore.create(
        tmp_path / "dinov2", rate=VIDEO_RATE, dim=8, encoder="dinov2"
    )
    # 10 s of audio, and pictures whose value is their frame index.
    audio.write(1, np.ones((100, 4), dtype=np.float16))
    video.write(1, np.repeat(np.arange(50, dtype=np.float16)[:, None], 8, axis=1))
    return tmp_path


@pytest.fixture()
def fused(features):
    store = open_store(features, "ast_ms+dinov2")
    assert isinstance(store, FusedStore)
    return store


class TestOpenStore:
    def test_a_single_key_is_a_plain_store(self, features):
        assert isinstance(open_store(features, "ast_ms"), EmbeddingStore)

    def test_a_missing_cache_makes_the_fusion_absent(self, features):
        assert open_store(features, "ast_ms+nope") is None

    def test_the_fused_key_round_trips(self, fused):
        assert fused.encoder == "ast_ms+dinov2"


class TestFusedStore:
    def test_runs_on_the_first_cache_grid(self, fused):
        assert fused.rate == AUDIO_RATE
        assert fused.steps(1) == 100

    def test_widths_add_up(self, fused):
        assert fused.dim == 12
        assert [(s.encoder, s.start, s.end) for s in fused.spans] == [
            ("ast_ms", 0, 4),
            ("dinov2", 4, 12),
        ]

    def test_each_step_takes_the_nearest_picture(self, fused):
        window = fused.window(1, 2.0, 1.0)

        # Steps centred on 2.05, 2.15 ... 2.95 s; pictures every 0.2 s.
        expected = np.rint((2.0 + (np.arange(10) + 0.5) * 0.1) * VIDEO_RATE)
        assert window[:, 4] == pytest.approx(expected)
        assert window[:, :4] == pytest.approx(np.ones((10, 4)))

    def test_the_whole_game_matches_its_windows(self, fused):
        whole = fused.load(1)

        assert whole.shape == (100, 12)
        assert whole[30:40] == pytest.approx(fused.window(1, 3.0, 1.0))

    def test_steps_past_the_last_picture_are_zero(self, fused):
        window = fused.window(1, 9.5, 1.0)

        assert (window[5:, 4:] == 0).all()

    def test_needs_every_cache(self, fused):
        assert fused.has(1)
        assert not fused.has(2)
