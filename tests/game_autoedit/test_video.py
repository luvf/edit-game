"""Tests for game_autoedit.data.video."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from game_autoedit.data.video import prefetched, read_frames

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


def _clip(path, seconds: float, colour: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", f"color=c={colour}:s=160x90:r=30:d={seconds}",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip


class TestReadFrames:
    def test_yields_rate_frames_a_second_at_the_asked_size(self, tmp_path):
        _clip(tmp_path / "a.mp4", 4.0, "red")

        batches = list(
            read_frames([tmp_path / "a.mp4"], rate=5, width=28, height=14, batch=8)
        )

        frames = np.concatenate(batches)
        assert frames.shape == (20, 14, 28, 3)
        assert all(len(batch) <= 8 for batch in batches)

    def test_reads_several_sources_back_to_back(self, tmp_path):
        _clip(tmp_path / "a.mp4", 2.0, "red")
        _clip(tmp_path / "b's.mp4", 2.0, "blue")

        frames = np.concatenate(
            list(
                read_frames(
                    [tmp_path / "a.mp4", tmp_path / "b's.mp4"],
                    rate=5,
                    width=28,
                    height=14,
                )
            )
        )

        assert len(frames) == 20
        assert frames[2, 7, 14, 0] > frames[2, 7, 14, 2]  # red first
        assert frames[17, 7, 14, 2] > frames[17, 7, 14, 0]  # then blue

    def test_reports_an_unreadable_file(self, tmp_path):
        (tmp_path / "bad.mp4").write_bytes(b"not a video")

        with pytest.raises(RuntimeError):
            list(read_frames([tmp_path / "bad.mp4"], rate=5, width=28, height=14))


class TestPrefetched:
    def test_yields_everything_in_order(self):
        batches = [np.full(2, index) for index in range(10)]

        assert [int(b[0]) for b in prefetched(iter(batches), depth=2)] == list(
            range(10)
        )

    def test_passes_the_reader_error_on(self):
        def failing():
            yield np.zeros(1)
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            list(prefetched(failing()))
