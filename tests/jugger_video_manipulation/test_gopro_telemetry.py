"""Tests for reading a GoPro's recorded orientation.

The GPMF buffers and the MP4 header are built by hand, block by block, so
each test says exactly what the camera wrote.
"""

from __future__ import annotations

import math
import struct
import subprocess

import numpy as np
import pytest

from jugger_video_manipulation.gopro_telemetry import (
    Settings,
    extract_track,
    multiply,
    parse_telemetry,
    read_settings,
    rotation_vectors,
)

SCALE = 32767


def klv(key: bytes, kind: str, size: int, repeat: int, payload: bytes) -> bytes:
    """One GPMF block: key, type, item size, repeat count, padded payload."""
    header = key + bytes([ord(kind), size]) + repeat.to_bytes(2, "big")
    return header + payload + b"\x00" * (-len(payload) % 4)


def nested(key: bytes, *children: bytes) -> bytes:
    inner = b"".join(children)
    return klv(key, "\x00", 1, len(inner), inner)


def quaternions(key: bytes, items) -> bytes:
    payload = b"".join(
        struct.pack(">4h", *(round(v * SCALE) for v in item)) for item in items
    )
    return klv(key, "s", 8, len(items), payload)


def text(key: bytes, value: str) -> bytes:
    return klv(key, "c", 1, len(value), value.encode())


def stream(*children: bytes) -> bytes:
    return nested(b"STRM", klv(b"SCAL", "s", 2, 1, struct.pack(">h", SCALE)), *children)


def about_z(degrees: float) -> tuple[float, float, float, float]:
    half = math.radians(degrees) / 2
    return (math.cos(half), 0.0, 0.0, math.sin(half))


IDENTITY = (1.0, 0.0, 0.0, 0.0)


class TestParseTelemetry:
    def test_one_orientation_per_frame(self):
        data = nested(
            b"DEVC",
            text(b"DVNM", "HERO10 Black"),
            stream(quaternions(b"CORI", [IDENTITY, about_z(10), about_z(20)])),
        )

        telemetry = parse_telemetry(data)

        assert telemetry.camera == "HERO10 Black"
        assert telemetry.orientations.shape == (3, 4)
        assert np.allclose(np.linalg.norm(telemetry.orientations, axis=1), 1.0)

    def test_batches_follow_one_another(self):
        # One DEVC per second of video: the frames run on across them.
        second = nested(b"DEVC", stream(quaternions(b"CORI", [about_z(5)] * 2)))
        data = second + second

        assert len(parse_telemetry(data).orientations) == 4

    def test_the_image_orientation_is_composed_in(self):
        # HyperSmooth's counter-rotation, when there is one, belongs to the
        # image: a camera turned 20° whose image was turned back 5° shows 15°.
        data = nested(
            b"DEVC",
            stream(quaternions(b"CORI", [about_z(20)])),
            stream(quaternions(b"IORI", [about_z(-5)])),
        )

        rotation = rotation_vectors(parse_telemetry(data).orientations)

        assert math.degrees(rotation[0, 2]) == pytest.approx(15, abs=0.05)

    def test_a_track_without_orientation_is_none(self):
        data = nested(b"DEVC", text(b"DVNM", "HERO5 Black"))

        assert parse_telemetry(data) is None

    def test_a_truncated_track_is_read_as_far_as_it_is_whole(self):
        # A copy cut short mid-block: the batch that is whole still counts,
        # the one that is not is dropped rather than read past its end.
        whole = nested(b"DEVC", stream(quaternions(b"CORI", [IDENTITY] * 3)))
        broken = nested(b"DEVC", stream(quaternions(b"CORI", [IDENTITY] * 3)))

        telemetry = parse_telemetry(whole + broken[:-7])

        assert len(telemetry.orientations) == 3

    def test_the_settings_are_carried_along(self):
        data = nested(b"DEVC", stream(quaternions(b"CORI", [IDENTITY])))
        settings = Settings(lens="S", diagonal_fov=148.0, hypersmooth="OFF")

        assert parse_telemetry(data, settings).settings == settings


class TestRotations:
    def test_no_rotation_is_a_zero_vector(self):
        assert np.allclose(rotation_vectors(np.array([IDENTITY])), 0.0)

    def test_the_angle_is_carried_by_the_length(self):
        rotation = rotation_vectors(np.array([about_z(90)]))

        assert rotation[0] == pytest.approx([0.0, 0.0, math.pi / 2])

    def test_a_quaternion_and_its_negative_are_the_same_rotation(self):
        q = np.array([about_z(30)])

        assert np.allclose(rotation_vectors(q), rotation_vectors(-q))

    def test_composing_adds_rotations_about_one_axis(self):
        combined = multiply(np.array([about_z(10)]), np.array([about_z(25)]))

        assert math.degrees(rotation_vectors(combined)[0, 2]) == pytest.approx(35)


def box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


class TestReadSettings:
    def test_it_reads_the_lens_from_the_header(self, tmp_path):
        gpmf = nested(
            b"DEVC",
            text(b"VFOV", "S"),
            klv(b"ZFOV", "f", 4, 1, struct.pack(">f", 148.0)),
            text(b"HSGT", "OFF"),
        )
        # A 64-bit mdat, as a four-gigabyte rush has, ahead of the header.
        mdat = (1).to_bytes(4, "big") + b"mdat" + (16 + 32).to_bytes(8, "big")
        mdat += b"GPMF" * 8
        path = tmp_path / "rush.mp4"
        path.write_bytes(
            box(b"ftyp", b"mp41")
            + mdat
            + box(b"moov", box(b"udta", box(b"GPMF", gpmf)))
        )

        assert read_settings(path) == Settings("S", 148.0, "OFF")

    def test_video_bytes_that_spell_gpmf_are_not_taken_for_the_header(self, tmp_path):
        path = tmp_path / "rush.mp4"
        path.write_bytes(box(b"mdat", b"GPMF" * 16) + box(b"moov", b""))

        assert read_settings(path) == Settings()

    def test_a_missing_file_gives_empty_settings(self, tmp_path):
        assert read_settings(tmp_path / "nowhere.mp4") == Settings()


class TestExtractTrack:
    def test_a_video_without_a_metadata_track_gives_nothing(self, tmp_path):
        # What an archive rendered by ffmpeg, or any export, looks like.
        clip = tmp_path / "export.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=64x36:rate=25:duration=1",
                "-c:v", "libx264", str(clip),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip

        assert extract_track(clip) == b""
