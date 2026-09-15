"""Reading the orientation a GoPro records alongside its video.

A GoPro writes a metadata track (`gpmd`) in the GPMF format: nested
key-length-value blocks, one batch per second of video. Among the streams in
it, `CORI` is the orientation of the camera and `IORI` the orientation of the
image relative to the camera — what the in-camera stabilisation did to it. A
HERO10 writes one of each per video frame, already in step with the frames.

The quaternions turn the world into the camera: the rotation from one frame
to another is `q · conj(q_ref)`, read in the camera's own axes — 0 across
the sensor, 1 up it, 2 along the lens. That order was measured rather than
assumed: against what vid.stab sees in the picture, it lines each axis up
with one image motion on every rush, where the reverse order mixes them
according to how the camera was pointing.

The image's orientation is then the image's own turn applied after the
camera's: with HyperSmooth off `IORI` stays at the identity and changes
nothing; with it on, it holds the counter-rotation. That second case follows
from the convention but has not been checked on footage shot with
HyperSmooth on.

The settings the whole file was shot with — the lens, its field of view,
whether HyperSmooth was on — are not in that track: they sit once in the MP4
header, in a `GPMF` box under `moov/udta`, in the same key-length-value form.

Nothing here draws or decodes video: the track is copied out with ffmpeg and
parsed in Python.
"""

from __future__ import annotations

import functools
import struct
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

#: struct format of each GPMF value type, big-endian.
_TYPES = {
    "b": "b",
    "B": "B",
    "c": "c",
    "d": "d",
    "f": "f",
    "j": "q",
    "J": "Q",
    "l": "i",
    "L": "I",
    "s": "h",
    "S": "H",
}

#: A quaternion has four components: w, x, y, z.
QUATERNION = 4

#: Below this, a rotation is taken as none: its axis cannot be told.
_NEGLIGIBLE = 1e-12


@dataclass(frozen=True)
class _Klv:
    key: str
    kind: str
    size: int
    repeat: int
    payload: bytes


def _walk(data: bytes) -> Iterator[_Klv]:
    """Yield every block of a GPMF buffer, descending into nested ones."""
    offset = 0
    header = 8
    while offset + header <= len(data):
        key = data[offset : offset + 4].decode("latin-1")
        kind = chr(data[offset + 4])
        size = data[offset + 5]
        repeat = int.from_bytes(data[offset + 6 : offset + 8], "big")
        length = size * repeat
        payload = data[offset + header : offset + header + length]
        if not key.isprintable() or len(payload) < length:
            return
        if kind == "\x00":
            yield from _walk(payload)
        else:
            yield _Klv(key, kind, size, repeat, payload)
        offset += header + (length + 3) // 4 * 4


def _values(block: _Klv) -> list[tuple[float, ...]]:
    """Decode a block into one tuple per repeat."""
    code = _TYPES.get(block.kind)
    if code is None:
        return []
    width = struct.calcsize(code)
    per_item = block.size // width
    fmt = f">{per_item}{code}"
    return [
        struct.unpack(fmt, block.payload[n * block.size : (n + 1) * block.size])
        for n in range(block.repeat)
    ]


def _text(block: _Klv) -> str:
    """Decode a character block."""
    return block.payload.decode("latin-1").rstrip("\x00").strip()


@dataclass(frozen=True)
class Telemetry:
    """What a GoPro recorded about its own position, frame by frame.

    Attributes:
        camera: the model name, `HERO10 Black` for instance.
        orientations: one unit quaternion per frame, `(frames, 4)` as
            w, x, y, z: the orientation of the image.
        settings: the file-wide settings from the MP4 header.
    """

    camera: str | None
    orientations: np.ndarray
    settings: Settings


@dataclass(frozen=True)
class Settings:
    """What the whole file was shot with, from the MP4 header.

    Attributes:
        lens: the field-of-view setting: `S` SuperView, `W` wide, `L` linear,
            `N` narrow, `H` linear with horizon levelling...
        diagonal_fov: the diagonal field of view, in degrees.
        hypersmooth: HyperSmooth's setting as written, `OFF` when it was off.
    """

    lens: str | None = None
    diagonal_fov: float | None = None
    hypersmooth: str | None = None


def extract_track(path: Path) -> bytes:
    """Return the raw GPMF track of a video, empty when it has none."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_tag_string",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    index = next(
        (
            line.split(",")[0]
            for line in probe.stdout.splitlines()
            if line.strip().endswith(",gpmd")
        ),
        None,
    )
    if probe.returncode != 0 or index is None:
        return b""
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            f"0:{index}",
            "-c",
            "copy",
            "-f",
            "data",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else b""


def parse_telemetry(data: bytes, settings: Settings | None = None) -> Telemetry | None:
    """Parse a GPMF track into per-frame image orientations.

    Returns:
        The telemetry, or None when the track holds no camera orientation —
        an older camera, or a file that went through an editor or an encode
        that did not keep the track.
    """
    camera = None
    scale = 1.0
    cameras: list[tuple[float, ...]] = []
    images: list[tuple[float, ...]] = []

    for block in _walk(data):
        if block.key == "DVNM" and camera is None:
            camera = _text(block)
        elif block.key == "SCAL":
            values = _values(block)
            scale = float(values[0][0]) if values else 1.0
        elif block.key in ("CORI", "IORI"):
            quaternions = [
                tuple(v / scale for v in item)
                for item in _values(block)
                if len(item) == QUATERNION
            ]
            (cameras if block.key == "CORI" else images).extend(quaternions)

    if not cameras:
        return None

    orientation = _normalise(np.asarray(cameras, dtype=float))
    if len(images) == len(cameras):
        orientation = _normalise(multiply(np.asarray(images, dtype=float), orientation))
    return Telemetry(camera, orientation, settings or Settings())


@functools.lru_cache(maxsize=64)
def read_telemetry(path: Path) -> Telemetry | None:
    """Return the telemetry of a video file, None when it carries none.

    Cached: the renders of one game read the same rushes, and a track is
    several megabytes to copy out and parse.
    """
    return parse_telemetry(extract_track(path), read_settings(path))


def _boxes(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Yield `(type, payload start, payload end)` for each MP4 box in a range."""
    position = start
    while position + 8 <= end:
        handle.seek(position)
        header = handle.read(16)
        size = int.from_bytes(header[:4], "big")
        kind = header[4:8]
        offset = 8
        if size == 1:
            size = int.from_bytes(header[8:16], "big")
            offset = 16
        elif size == 0:
            size = end - position
        if size < offset:
            return
        yield kind, position + offset, position + size
        position += size


def _child(
    handle: BinaryIO, start: int, end: int, kind: bytes
) -> tuple[int, int] | None:
    return next(
        (
            (begin, finish)
            for name, begin, finish in _boxes(handle, start, end)
            if name == kind
        ),
        None,
    )


def read_settings(path: Path) -> Settings:
    """Return the lens and stabilisation settings from a GoPro MP4's header.

    Walks the box tree rather than searching for the bytes: `mdat` holds
    gigabytes of video in which any four letters can turn up by chance.
    """
    try:
        with path.open("rb") as handle:
            end = handle.seek(0, 2)
            moov = _child(handle, 0, end, b"moov")
            udta = moov and _child(handle, *moov, b"udta")
            gpmf = udta and _child(handle, *udta, b"GPMF")
            if not gpmf:
                return Settings()
            handle.seek(gpmf[0])
            data = handle.read(gpmf[1] - gpmf[0])
    except OSError:
        return Settings()

    lens = hypersmooth = None
    diagonal_fov = None
    for block in _walk(data):
        if block.key == "VFOV" and lens is None:
            lens = _text(block)
        elif block.key == "ZFOV" and diagonal_fov is None:
            values = _values(block)
            diagonal_fov = float(values[0][0]) if values else None
        elif block.key == "HSGT" and hypersmooth is None:
            hypersmooth = _text(block)
    return Settings(lens, diagonal_fov, hypersmooth)


def _normalise(quaternions: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    unit: np.ndarray = quaternions / np.where(norms == 0, 1.0, norms)
    return unit


def conjugate(quaternions: np.ndarray) -> np.ndarray:
    """Return the inverse of unit quaternions."""
    inverse: np.ndarray = quaternions * np.array([1.0, -1.0, -1.0, -1.0])
    return inverse


def multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return the Hamilton product of two arrays of quaternions."""
    w1, x1, y1, z1 = np.moveaxis(a, -1, 0)
    w2, x2, y2, z2 = np.moveaxis(b, -1, 0)
    product: np.ndarray = np.stack(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        axis=-1,
    )
    return product


def rotation_vectors(quaternions: np.ndarray) -> np.ndarray:
    """Return each rotation as an axis scaled by its angle, in radians."""
    unit = _normalise(np.atleast_2d(quaternions))
    unit = unit * np.where(unit[:, :1] < 0, -1.0, 1.0)
    sine = np.linalg.norm(unit[:, 1:], axis=1)
    angle = 2.0 * np.arctan2(sine, unit[:, 0])
    tiny = sine <= _NEGLIGIBLE
    factor = np.where(tiny, 2.0, angle / np.where(tiny, 1.0, sine))
    vectors: np.ndarray = unit[:, 1:] * factor[:, None]
    return vectors
