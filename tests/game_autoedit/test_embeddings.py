"""Tests for game_autoedit.data.embeddings."""

from __future__ import annotations

import numpy as np
import pytest

from game_autoedit.data.embeddings import EmbeddingStore

RATE = 10.0
DIM = 8


@pytest.fixture()
def store(tmp_path):
    store = EmbeddingStore.create(tmp_path / "ast", rate=RATE, dim=DIM, encoder="ast")
    steps = 100
    values = np.arange(steps * DIM, dtype=np.float16).reshape(steps, DIM)
    store.write(1, values)
    return store


class TestStore:
    def test_reopens_with_the_same_metadata(self, store):
        reopened = EmbeddingStore.open(store.root)

        assert reopened is not None
        assert (reopened.rate, reopened.dim, reopened.encoder) == (RATE, DIM, "ast")

    def test_open_returns_none_when_absent(self, tmp_path):
        assert EmbeddingStore.open(tmp_path / "nope") is None

    def test_hop_is_the_inverse_rate(self, store):
        assert store.hop == pytest.approx(0.1)

    def test_reports_presence(self, store):
        assert store.has(1) is True
        assert store.has(2) is False

    def test_counts_steps_without_loading(self, store):
        assert store.steps(1) == 100

    def test_leaves_no_partial_file(self, store):
        assert list(store.root.glob("*.partial.npy")) == []


class TestWindow:
    def test_returns_the_requested_length(self, store):
        window = store.window(1, 1.0, 2.0)

        assert window.shape == (20, DIM)
        assert window.dtype == np.float32

    def test_reads_from_the_right_offset(self, store):
        whole = store.window(1, 0.0, 10.0)
        window = store.window(1, 5.0, 1.0)

        assert window == pytest.approx(whole[50:60])

    def test_pads_past_the_end(self, store):
        window = store.window(1, 9.0, 3.0)

        assert window.shape == (30, DIM)
        assert window[10:] == pytest.approx(np.zeros((20, DIM)))

    def test_window_entirely_past_the_end_is_zero(self, store):
        assert store.window(1, 50.0, 1.0) == pytest.approx(np.zeros((10, DIM)))
