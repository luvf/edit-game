"""Steadying the kept points of a cut against a camera swaying in the wind.

The camera sits on a tripod with an extension pole; what moves it is the wind,
and what it does is sway — a slow drift and a roll of about a degree. Measured
on the rushes, rotation is what costs the picture: one degree of roll on a
16:9 frame already eats 3.5 % of its height, the sideways sway is negligible
next to it.

Where each frame pointed comes from one of two places, and each is corrected
the way that suits it:

- **the camera itself.** A GoPro records its orientation for every frame, in
  a metadata track of the MP4. Nothing is analysed: the rotations are turned
  into image shifts, written in vid.stab's own text format, and applied in
  *tripod* mode — every frame moved back onto the point's average course, so
  the field does not move for the length of the point. The measurement cannot
  be fooled by players crossing the frame.
- **the picture**, when the video carries no usable track — another camera,
  a model not yet calibrated, a file that went through an export. vid.stab
  analyses each point and corrects it in *relative* mode, smoothing the camera
  path over about a second. Its tripod mode, matching pixels against a frame
  seconds away, only removed half the sway on these rushes; relative mode
  removed nine tenths of it, for less crop.

The gyroscope's files carry a marker, so the render knows which correction to
apply to what it reads.

Each kept point is analysed and steadied on its own, never the whole game: a
point is a separate shot, the camera is often touched between two of them.
And the analysis only ever reads what the render keeps: it seeks straight to
each point inside the rush that holds it, rather than decoding the rushes from
their start — which on a match an hour long is most of the work.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from jugger_video_manipulation.ffmpeg_utils import _add_input_files
from jugger_video_manipulation.gopro_telemetry import (
    conjugate,
    multiply,
    read_telemetry,
    rotation_vectors,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from jugger_video_manipulation.cut_json_parser import Point


@dataclass(frozen=True)
class StabiliseSettings:
    """How the camera path is measured and corrected.

    Attributes:
        shakiness: how shaky the footage is, 1 to 10. A tripod in the wind is
            mild: 4 finds the sway without taking the players for camera
            motion.
        accuracy: detection accuracy, 1 to 15. The analysis is paid once per
            render and a missed rotation shows, so the highest.
        stepsize: the search step in pixels; 6 is vidstab's own default.
        smoothing_seconds: how far either side of a frame the picture's
            camera path is averaged, in relative mode. About a second removes
            the sway while following the drift.
        relative_zoom: the crop of the relative correction, which follows the
            drift and so needs less of it: 1.9 and 3.3 % measured, 5 % kept.
        zoom: how far the picture is enlarged, in percent, to hide the edges
            a realigned frame no longer covers. Fixed rather than computed:
            the loss is known in advance and the same from one point to the
            next, where vidstab's optimal zoom would size itself on the worst
            gust of each point. The windiest plan measured needs 7.7 %.
    """

    shakiness: int = 4
    accuracy: int = 15
    stepsize: int = 6
    smoothing_seconds: float = 1.0
    relative_zoom: float = 5.0
    zoom: float = 8.0


@dataclass(frozen=True)
class Piece:
    """The part of one point that one rush holds, in that rush's frames."""

    file_index: int
    start: int
    end: int

    @property
    def frames(self) -> int:
        """Return how many frames the piece holds."""
        return self.end - self.start


def kept_points(points: Sequence[Point]) -> list[Point]:
    """Return the points that put frames in the render, in order.

    Same rule as `filter_cut` and `place_segments`: a point whose `out` does
    not come after its `in` contributes nothing, and gets no analysis either.
    """
    return [point for point in points if int(point["out"]) > int(point["in"])]


def point_pieces(point: Point, frame_counts: Sequence[int]) -> list[Piece]:
    """Split a point into the stretches each rush holds.

    Most points sit inside one rush. One that runs across the end of a rush
    comes back as two pieces, read from two files and joined again before
    the analysis sees them.
    """
    start, end = int(point["in"]), int(point["out"])
    pieces: list[Piece] = []
    offset = 0
    for index, count in enumerate(frame_counts):
        local_start = max(start - offset, 0)
        local_end = min(end - offset, count)
        if local_end > local_start:
            pieces.append(Piece(index, local_start, local_end))
        offset += count
    return pieces


def transform_paths(directory: Path, count: int) -> list[Path]:
    """Return where each kept point's camera path is written, one per point."""
    return [directory / f"point_{index:03d}.trf" for index in range(count)]


def _filter_value(path: Path) -> str:
    r"""Escape a path to sit as a filter option value in a filtergraph.

    Two levels, as ffmpeg parses them: the option value first (`\\`, `'`,
    `:`), then the graph around it (`\\`, `'`, `[`, `]`, `,`, `;`).
    """
    value = str(path)
    for char in ("\\", "'", ":"):
        value = value.replace(char, "\\" + char)
    for char in ("\\", "'", "[", "]", ",", ";"):
        value = value.replace(char, "\\" + char)
    return value


#: Left in a stabilisation directory by the gyroscope path: the files there are
#: corrections to apply in tripod mode, not camera paths to smooth.
GYRO_MARKER = "from_gyro"


@dataclass(frozen=True)
class GyroCalibration:
    """How one camera and lens turn a rotation of the camera into image motion.

    Attributes:
        focal_1080: vertical focal length in pixels of a 1080-line frame: how
            far the image moves when the camera tips by one radian.
        roll: the share of the camera's roll that shows as a rotation of the
            image.
    """

    focal_1080: float
    roll: float = 1.0


#: Measured, not derived, per camera model and lens setting, by rendering a
#: point with each candidate and measuring the motion left. On two rushes of
#: WCC Dresde shot with the camera pointing differently, 600 px and three
#: quarters of the roll left 0.3 and 0.5 px of vertical sway and 0.02° and
#: 0.06° of roll, from 8.7 px / 0.49° and 17.2 px / 1.34°: 450 and 750 px did
#: worse on at least one rush, as did a half or the whole of the roll.
#: SuperView stretches the sensor unevenly, which is the likeliest reason a
#: turn of the camera does not come out as the same turn of the picture.
#: The same lens setting on another model may not have the same field: a pair
#: not listed here is steadied from the picture instead.
GYRO_CALIBRATIONS: dict[tuple[str, str], GyroCalibration] = {
    ("HERO10 Black", "S"): GyroCalibration(focal_1080=600.0, roll=0.75),
}

#: What vid.stab is handed. Its ffmpeg wrapper advertises formats the library
#: cannot take — a 4:4:4 frame aborts the whole process on an assertion — so
#: the frames are pinned to 4:2:0, which the rushes already are: no conversion
#: happens on them, only on a source that would have crashed.
PIXEL_FORMATS = "yuvj420p|yuv420p"


def detect_filter(path: Path, settings: StabiliseSettings) -> str:
    """Return the analysis pass for one point, writing its camera path."""
    return (
        f"format=pix_fmts={PIXEL_FORMATS},"
        f"vidstabdetect=shakiness={settings.shakiness}"
        f":accuracy={settings.accuracy}:stepsize={settings.stepsize}"
        f":result={_filter_value(path)}"
    )


def transform_filter(path: Path, settings: StabiliseSettings) -> str:
    """Return the correction for one point, reading the path its analysis wrote.

    `tripod=1` is vidstab's own shorthand for absolute transforms and no
    smoothing: each frame is moved back onto the reference, not onto an
    average of its neighbours.
    """
    return (
        f"format=pix_fmts={PIXEL_FORMATS},"
        f"vidstabtransform=input={_filter_value(path)}:tripod=1"
        f":optzoom=0:zoom={settings.zoom:g}:crop=keep:interpol=bicubic"
    )


def relative_transform_filter(
    path: Path, fps: float, settings: StabiliseSettings
) -> str:
    """Return the correction for a camera path vid.stab measured in the picture.

    Relative: the path is smoothed and only what departs from the smoothed
    path is taken out. `smoothing` counts frames on either side, so it comes
    from the frame rate: a second at 60 fps is not a second at 25.
    """
    smoothing = max(round(fps * settings.smoothing_seconds), 1)
    return (
        f"format=pix_fmts={PIXEL_FORMATS},"
        f"vidstabtransform=input={_filter_value(path)}"
        f":smoothing={smoothing}:relative=1"
        f":optzoom=0:zoom={settings.relative_zoom:g}:crop=keep:interpol=bicubic"
    )


def detect_command(
    *,
    input_files: Sequence[Path],
    frame_counts: Sequence[int],
    fps: float,
    points: Sequence[Point],
    directory: Path,
    settings: StabiliseSettings | None = None,
    cuda_decode: bool = False,
) -> list[str]:
    """Build the analysis pass: every kept point measured, nothing encoded.

    Each piece of a point is its own input, sought to half a frame before its
    first frame: the seek lands between two frames, so rounding cannot move it
    onto the wrong one, and ffmpeg decodes from the keyframe before it rather
    than from the start of the rush. `trim=end_frame` then keeps exactly as
    many frames as the point holds.

    The render picks the same frames by the same arithmetic — `frame_bounds`
    puts its trims half a frame back too — and that matters:
    `vidstabtransform` reads its camera path frame by frame from the start of
    its input, and a point one frame late would get every correction one frame
    late.

    Args:
        input_files: the sources, in the order the render concatenates them.
        frame_counts: how many frames each source holds, from
            `ffmpeg_utils.probe_frame_counts`.
        fps: the frame rate the cut's points are counted in.
        points: the cut's points.
        directory: where the camera paths are written, `transform_paths`.
        settings: how the analysis is tuned.
        cuda_decode: decode on the GPU, as the render will.

    Returns:
        The ffmpeg command, ready for a subprocess.
    """
    settings = settings or StabiliseSettings()
    kept = kept_points(points)
    paths = transform_paths(directory, len(kept))

    inputs: list[str] = []
    graph: list[str] = []
    analysed: list[str] = []
    input_index = 0
    for number, (point, path) in enumerate(zip(kept, paths, strict=True)):
        labels: list[str] = []
        for piece in point_pieces(point, frame_counts):
            if piece.start > 0:
                inputs += ["-ss", f"{(piece.start - 0.5) / fps:.6f}"]
            inputs += _add_input_files(
                [input_files[piece.file_index]], decode_cuda_available=cuda_decode
            )
            label = f"[p{number}_{input_index}]"
            graph.append(
                f"[{input_index}:v:0]trim=end_frame={piece.frames},"
                f"setpts=PTS-STARTPTS{label}"
            )
            labels.append(label)
            input_index += 1

        joined = "".join(labels) + (
            f"concat=n={len(labels)}:v=1:a=0," if len(labels) > 1 else "null,"
        )
        output = f"[d{number}]"
        graph.append(f"{joined}{detect_filter(path, settings)}{output}")
        analysed.append(output)

    graph.append(f"{''.join(analysed)}concat=n={len(analysed)}:v=1:a=0[analysed]")

    return [
        "ffmpeg",
        "-nostdin",
        *inputs,
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[analysed]",
        "-f",
        "null",
        "-",
    ]


#: How much orientation a file may lack at its end, in seconds. A GoPro writes
#: its telemetry in one-second batches and leaves the last, partial one out:
#: the final chapter of a recording comes up to a second short of its frames.
TELEMETRY_SHORTFALL_SECONDS = 1.0


@dataclass(frozen=True)
class GyroSource:
    """The recorded orientation of every source, ready to steady points with.

    Attributes:
        orientations: one array per source, in the order the render
            concatenates them, holding one orientation per frame.
        frame_counts: how many frames each source holds.
        focal: the vertical focal length at the sources' own height.
        roll: the share of the camera's roll to correct.
    """

    orientations: Sequence[np.ndarray]
    frame_counts: Sequence[int]
    focal: float
    roll: float = 1.0


def _fit(orientations: np.ndarray, frames: int, tolerance: int) -> np.ndarray | None:
    """Return exactly one orientation per frame, or None if too many are missing.

    Frames past the last batch keep the last recorded orientation: under a
    second of a camera on a tripod, left as it was rather than guessed.
    """
    missing = frames - len(orientations)
    if len(orientations) == 0 or missing > tolerance:
        return None
    if missing <= 0:
        fitted: np.ndarray = orientations[:frames]
        return fitted
    return np.concatenate([orientations, np.repeat(orientations[-1:], missing, axis=0)])


def gyro_source(
    files: Sequence[Path], frame_counts: Sequence[int], height: int, fps: float
) -> GyroSource | None:
    """Return the sources' recorded orientation, when it can be used.

    Every source must carry the orientation of its frames — all of them, bar
    the partial second a GoPro leaves off the end of a recording — shot with
    one camera and lens this module has a calibration for. Anything less and
    the render analyses the picture, as it would for any other camera.
    """
    telemetry = [read_telemetry(path) for path in files]
    if any(item is None for item in telemetry):
        return None
    usable = [item for item in telemetry if item is not None]
    setups = {(item.camera, item.settings.lens) for item in usable}
    if len(setups) != 1:
        return None
    camera, lens = setups.pop()
    if camera is None or lens is None:
        return None
    calibration = GYRO_CALIBRATIONS.get((camera, lens))
    if calibration is None:
        return None

    tolerance = math.ceil(fps * TELEMETRY_SHORTFALL_SECONDS)
    fitted = [
        _fit(item.orientations, count, tolerance)
        for item, count in zip(usable, frame_counts, strict=True)
    ]
    if any(orientations is None for orientations in fitted):
        return None
    return GyroSource(
        [orientations for orientations in fitted if orientations is not None],
        list(frame_counts),
        focal=calibration.focal_1080 * height / 1080,
        roll=calibration.roll,
    )


def gyro_rotations(point: Point, source: GyroSource) -> np.ndarray:
    """Return how far each frame of a point is turned from where it should sit.

    Where it should sit is the point's own average course, not its middle
    frame: each axis's straight-line trend is taken out. The gyroscope's
    heading drifts — about 3.5 px a second sideways on these rushes, with the
    picture itself not moving — and locking onto one frame turns that drift
    into a slow slide of the corrected picture, off the edge of the crop on a
    long point. Taking the line out keeps the sway corrected and lets a real
    slow change of heading be followed rather than fought.

    Returns:
        `(frames, 3)` rotation vectors, in radians, one per frame of the point
        as the render plays it — pieces from several rushes joined in order.
        In the camera's own axes: 0 tips the view up and down, 1 turns it
        sideways, 2 rolls it about the lens.

    The GoPro's quaternions turn the world into the camera, so the turn
    from the reference is `q · conj(q_ref)`. The other order also gives
    rotations of the right size, with their axes mixed by however the
    camera happened to be pointing — which matched vid.stab on one rush and
    put 16 px of sideways sway into the next.
    """
    orientations = np.concatenate(
        [
            source.orientations[piece.file_index][piece.start : piece.end]
            for piece in point_pieces(point, source.frame_counts)
        ]
    )
    reference = orientations[len(orientations) // 2]
    turns = rotation_vectors(multiply(orientations, conjugate(reference[None, :])))
    return _without_trend(turns)


def _without_trend(turns: np.ndarray) -> np.ndarray:
    """Take each axis's least-squares straight line out of a point's turns."""
    if len(turns) < 2:  # noqa: PLR2004 — a line needs two frames
        centred_only: np.ndarray = turns - turns.mean(axis=0)
        return centred_only
    time = np.arange(len(turns), dtype=float)
    time -= time.mean()
    centred = turns - turns.mean(axis=0)
    slope = (time @ centred) / (time @ time)
    residual: np.ndarray = centred - np.outer(time, slope)
    return residual


def write_gyro_transforms(
    path: Path, rotations: np.ndarray, focal: float, roll: float = 1.0
) -> None:
    """Write a point's camera path in the text format vid.stab reads.

    One line per frame: its number, the shift in x and y in pixels, the
    rotation in radians, then zoom and a flag vid.stab leaves at zero. The
    signs are vid.stab's, measured against its own analysis of the same
    frames on two rushes shot with the camera pointing differently, and
    consistent on both.
    """
    lines = ["# camera path from the GoPro's recorded orientation\n"]
    for index, (tip, sideways, turn) in enumerate(rotations):
        x = -focal * sideways
        y = focal * tip
        angle = roll * turn
        lines.append(f"{index} {x:.4f} {y:.4f} {angle:.7f} 0 0\n")
    path.write_text("".join(lines))


def write_gyro_paths(
    points: Sequence[Point], directory: Path, source: GyroSource
) -> None:
    """Write every kept point's camera path from the recorded orientation.

    The files land where the analysis would have written them, so the render
    reads them without knowing where they came from.
    """
    kept = kept_points(points)
    for path, point in zip(transform_paths(directory, len(kept)), kept, strict=True):
        write_gyro_transforms(
            path, gyro_rotations(point, source), source.focal, source.roll
        )
    (directory / GYRO_MARKER).write_text("orientation enregistrée par la caméra\n")


def wrote_from_gyro(directory: Path) -> bool:
    """Tell whether a stabilisation directory was filled from the gyroscope."""
    return (directory / GYRO_MARKER).exists()


def transform_filters(
    points: Sequence[Point],
    directory: Path,
    *,
    fps: float,
    from_gyro: bool,
    settings: StabiliseSettings | None = None,
) -> list[str]:
    """Return the correction for each kept point, for `filter_cut`.

    Tripod for the gyroscope's corrections, relative for the camera paths
    vid.stab measured in the picture — see the module docstring.
    """
    settings = settings or StabiliseSettings()
    paths = transform_paths(directory, len(kept_points(points)))
    if from_gyro:
        return [transform_filter(path, settings) for path in paths]
    return [relative_transform_filter(path, fps, settings) for path in paths]
