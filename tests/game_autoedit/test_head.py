"""Tests for game_autoedit.models.head."""

from __future__ import annotations

import torch

from game_autoedit.datasets.targets import CHANNELS
from game_autoedit.models.head import EmbeddingTagger, HeadSpec

DIM = 32


class TestHeadSpec:
    def test_receptive_field_grows_with_dilations(self):
        small = HeadSpec(dilations=(1, 2, 4))
        large = HeadSpec(dilations=(1, 2, 4, 8, 16))

        assert large.receptive_field() > small.receptive_field()

    def test_receptive_field_matches_the_formula(self):
        spec = HeadSpec(dilations=(1, 2, 4))

        assert spec.receptive_field() == 1 + 4 * (1 + 2 + 4)


class TestEmbeddingTagger:
    def test_predicts_one_step_per_input_step(self):
        model = EmbeddingTagger(DIM, HeadSpec(channels=16, dilations=(1, 2)))
        out = model(torch.randn(2, 50, DIM))

        assert out.shape == (2, 50, len(CHANNELS))

    def test_same_weights_run_on_any_length(self):
        model = EmbeddingTagger(DIM, HeadSpec(channels=16, dilations=(1, 2))).eval()

        short = model(torch.randn(1, 40, DIM))
        long = model(torch.randn(1, 4000, DIM))

        assert short.shape[1] == 40
        assert long.shape[1] == 4000

    def test_a_whole_game_matches_a_slice_of_it(self):
        torch.manual_seed(0)
        model = EmbeddingTagger(DIM, HeadSpec(channels=16, dilations=(1, 2))).eval()
        game = torch.randn(1, 600, DIM)

        with torch.no_grad():
            whole = model(game)
            # Far from the edges, a slice must give the same answer as the
            # whole sequence: that is what makes single-pass inference sound.
            piece = model(game[:, 100:500])

        assert torch.allclose(whole[:, 200:400], piece[:, 100:300], atol=1e-5)

    def test_stays_small(self):
        model = EmbeddingTagger(768, HeadSpec())

        assert sum(p.numel() for p in model.parameters()) < 2_000_000
