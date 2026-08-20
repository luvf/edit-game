"""Tests for jugger_video_manipulation.utils (pure helpers only)."""

from __future__ import annotations

import pytest

from jugger_video_manipulation.utils import get_ms_time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (59, "00:59"),
        (60, "01:00"),
        (61.9, "01:01"),
        ("125", "02:05"),
        (3661, "61:01"),
    ],
)
def test_get_ms_time(seconds, expected):
    assert get_ms_time(seconds) == expected
