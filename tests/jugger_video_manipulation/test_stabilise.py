"""Tests for the per-point stabilisation."""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from jugger_video_manipulation import stabilise as stabilise_module
from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    probe_frame_counts,
)
from jugger_video_manipulation.gopro_telemetry import Settings, Telemetry, multiply
from jugger_video_manipulation.stabilise import (
    GYRO_CALIBRATIONS,
    GyroSource,
    Piece,
    StabiliseSettings,
    _filter_value,
    detect_command,
    detect_filter,
    gyro_rotations,
    gyro_source,
    kept_points,
    point_pieces,
    relative_transform_filter,
    transform_filter,
    transform_filters,
    transform_paths,
    write_gyro_paths,
    write_gyro_transforms,
    wrote_from_gyro,
)

FPS = 25.0


def point(start, end):
    return {"in": start, "out": end, "point": None}


def graph_of(command):
    return command[command.index("-filter_complex") + 1]


class TestKeptPoints:
    def test_a_point_that_keeps_nothing_gets_no_analysis(self):
        assert kept_points([point(0, 250), point(300, 300), point(500, 400)]) == [
            point(0, 250)
        ]


class TestPointPieces:
    def test_a_point_inside_a_rush_is_one_piece_in_that_rush_s_frames(self):
        assert point_pieces(point(1200, 1500), [1000, 1000]) == [Piece(1, 200, 500)]

    def test_a_point_across_the_end_of_a_rush_is_two_pieces(self):
        assert point_pieces(point(900, 1100), [1000, 1000]) == [
            Piece(0, 900, 1000),
            Piece(1, 0, 100),
        ]

    def test_a_rush_it_spans_entirely_is_read_whole(self):
        assert point_pieces(point(900, 2100), [1000, 1000, 1000]) == [
            Piece(0, 900, 1000),
            Piece(1, 0, 1000),
            Piece(2, 0, 100),
        ]

    def test_what_runs_past_the_last_rush_is_not_invented(self):
        assert point_pieces(point(900, 5000), [1000]) == [Piece(0, 900, 1000)]


class TestFilters:
    def test_one_camera_path_per_kept_point(self, tmp_path):
        assert [path.name for path in transform_paths(tmp_path, 2)] == [
            "point_000.trf",
            "point_001.trf",
        ]

    def test_the_analysis_writes_where_the_correction_reads(self, tmp_path):
        path = tmp_path / "point_000.trf"
        settings = StabiliseSettings()

        assert f"result={path}" in detect_filter(path, settings)
        assert f"input={path}" in transform_filter(path, settings)

    def test_every_frame_is_moved_back_onto_the_reference(self, tmp_path):
        # Absolute transforms, no smoothing: the field does not drift at all,
        # where a smoothed path would follow the pole leaning in the wind.
        text = transform_filter(tmp_path / "p", StabiliseSettings())

        assert ":tripod=1:" in text
        assert "smoothing" not in text
        assert "relative" not in text

    def test_the_analysis_measures_the_path_frame_to_frame(self, tmp_path):
        # The picture's path is smoothed, not locked: no reference frame.
        assert "tripod" not in detect_filter(tmp_path / "p", StabiliseSettings())

    def test_a_measured_path_is_smoothed_over_a_second(self, tmp_path):
        path = tmp_path / "p.trf"

        assert "smoothing=25:" in relative_transform_filter(
            path, 25.0, StabiliseSettings()
        )
        assert "smoothing=60:" in relative_transform_filter(
            path, 59.94, StabiliseSettings()
        )

    def test_a_measured_path_follows_the_drift_with_less_crop(self, tmp_path):
        text = relative_transform_filter(tmp_path / "p", 25.0, StabiliseSettings())

        assert ":relative=1:" in text
        assert ":zoom=5:" in text
        assert "tripod" not in text

    def test_the_zoom_is_fixed_rather_than_computed(self, tmp_path):
        text = transform_filter(tmp_path / "p", StabiliseSettings(zoom=5.0))

        assert "optzoom=0" in text
        assert "zoom=5:" in text

    def test_vidstab_is_only_handed_frames_it_can_take(self, tmp_path):
        settings = StabiliseSettings()

        for text in (
            detect_filter(tmp_path / "p", settings),
            transform_filter(tmp_path / "p", settings),
        ):
            assert text.startswith("format=pix_fmts=yuvj420p|yuv420p,vidstab")

    def test_a_4_4_4_source_does_not_abort_the_analysis(self, tmp_path):
        # vid.stab asserts on a 4:4:4 frame and takes ffmpeg down with it;
        # the format pin is what stands between a render and that abort.
        clip = tmp_path / "full.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=96x54:rate=25:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuvj444p", str(clip),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        path = tmp_path / "p.trf"

        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                "-vf", detect_filter(path, StabiliseSettings()), "-f", "null", "-",
            ],
            capture_output=True,
            text=True, check=False,
        )  # fmt: skip

        assert result.returncode == 0, result.stderr
        assert path.stat().st_size > 0

    def test_a_plain_path_is_left_as_is(self):
        path = "/tmp/work/point_000.trf"

        assert _filter_value(Path(path)) == path

    def test_a_colon_cannot_split_the_options(self):
        # Unescaped, `:` would end the value and start an unknown option.
        assert ":" not in _filter_value(Path("/tmp/a:b.trf")).replace("\\:", "")


class TestDetectCommand:
    """Only the kept frames are read, straight from the rush holding them."""

    RUSHES = (1000, 1000)

    @pytest.fixture()
    def command(self, tmp_path):
        return detect_command(
            input_files=[tmp_path / "a.mp4", tmp_path / "b.mp4"],
            frame_counts=self.RUSHES,
            fps=FPS,
            points=[point(250, 500), point(900, 1100), point(1500, 1750)],
            directory=tmp_path / "stab",
        )

    def test_it_encodes_nothing(self, command):
        assert command[-3:] == ["-f", "null", "-"]

    def test_each_kept_point_is_analysed_once(self, command):
        assert graph_of(command).count("vidstabdetect=") == 3

    def test_each_piece_is_its_own_input(self, command, tmp_path):
        # Three points, one of which runs across the end of the first rush.
        inputs = [command[i + 1] for i, arg in enumerate(command) if arg == "-i"]

        assert inputs == [
            str((tmp_path / name).absolute())
            for name in ("a.mp4", "a.mp4", "b.mp4", "b.mp4")
        ]

    def test_it_seeks_rather_than_decoding_from_the_start(self, command):
        # Half a frame before each piece, so rounding cannot land it a frame
        # early or late; a piece starting its rush needs no seek at all.
        seeks = [command[i + 1] for i, arg in enumerate(command) if arg == "-ss"]

        assert seeks == [
            f"{249.5 / FPS:.6f}",
            f"{899.5 / FPS:.6f}",
            f"{499.5 / FPS:.6f}",
        ]

    def test_each_piece_keeps_exactly_its_frames(self, command):
        assert re.findall(r"end_frame=(\d+)", graph_of(command)) == [
            "250",
            "100",
            "100",
            "250",
        ]

    def test_a_point_across_two_rushes_is_joined_before_it_is_analysed(self, command):
        chain = next(
            part
            for part in graph_of(command).split(";")
            if "vidstabdetect" in part and "point_001" in part
        )

        assert chain.startswith("[p1_1][p1_2]concat=n=2:v=1:a=0,format=")
        assert "vidstabdetect" in chain

    def test_it_decodes_on_the_gpu_only_when_asked(self, tmp_path):
        common = {
            "input_files": [tmp_path / "a.mp4"],
            "frame_counts": [1000],
            "fps": FPS,
            "points": [point(0, 250)],
            "directory": tmp_path,
        }

        assert "-hwaccel" in detect_command(**common, cuda_decode=True)
        assert "-hwaccel" not in detect_command(**common)


class TestFilterCutTakesAChainPerPoint:
    def test_the_chain_follows_the_trim(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        builder.filter_cut(FPS, [point(0, 250)], video_filters=["hflip"])

        assert "setpts=PTS-STARTPTS,hflip[sv0_" in builder.get_filter_complex()

    def test_the_chains_must_match_the_kept_points(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)

        with pytest.raises(ValueError, match="kept points"):
            builder.filter_cut(
                FPS, [point(0, 250), point(500, 750)], video_filters=["hflip"]
            )


def _clip(path, frames):
    """A short clip whose every frame differs, with keyframes to seek between."""
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=96x54:rate={FPS:g}",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-frames:v", str(frames), "-shortest",
            "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def _video_hashes(framemd5):
    """Return the hash of every video frame a framemd5 listing holds."""
    return [
        line.rsplit(",", 1)[1].strip()
        for line in framemd5.read_text().splitlines()
        if line and not line.startswith("#") and line.split(",")[0].strip() == "0"
    ]


class TestBothPassesSeeTheSameFrames:
    """The one property the correction depends on, checked with ffmpeg itself.

    `vidstabtransform` reads its camera path frame by frame: if the render
    handed it a point starting one frame off from what the analysis measured,
    every correction would be applied to the wrong frame.
    """

    def test_seeking_into_the_rushes_matches_cutting_their_concatenation(
        self, tmp_path
    ):
        rushes = [_clip(tmp_path / "a.mp4", 60), _clip(tmp_path / "b.mp4", 60)]
        points = [point(7, 23), point(50, 71), point(95, 110)]
        counts = probe_frame_counts(rushes)
        assert counts == [60, 60]

        analysis = detect_command(
            input_files=rushes,
            frame_counts=counts,
            fps=FPS,
            points=points,
            directory=tmp_path,
        )
        # Same frames, hashed instead of analysed.
        analysis = [re.sub(r"vidstabdetect=[^\[]+", "null", arg) for arg in analysis]
        analysis_hashes = tmp_path / "analysis.txt"
        subprocess.run(
            [*analysis[:-3], "-f", "framemd5", str(analysis_hashes)],
            check=True,
            capture_output=True,
        )

        render = FilterComplexBuilder(len(rushes))
        render.filter_concat(render.inputs_v, render.inputs_a)
        render.filter_cut(FPS, points, video_filters=["null"] * len(points))
        render_hashes = tmp_path / "render.txt"
        inputs = [arg for rush in rushes for arg in ("-i", str(rush))]
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", *inputs,
                "-filter_complex", render.get_filter_complex(),
                "-map", render.out_v, "-map", render.out_a,
                "-f", "framemd5", str(render_hashes),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip

        render_frames = _video_hashes(render_hashes)
        assert len(render_frames) == 16 + 21 + 15
        assert _video_hashes(analysis_hashes) == render_frames


def turned(axis, degrees):
    """A quaternion for a turn about one of the GoPro's axes."""
    half = math.radians(degrees) / 2
    q = [math.cos(half), 0.0, 0.0, 0.0]
    q[axis + 1] = math.sin(half)
    return q


def recorded(orientations, lens="S"):
    return Telemetry(
        camera="HERO10 Black",
        orientations=np.asarray(orientations, dtype=float),
        settings=Settings(lens=lens),
    )


def still(frames, lens="S"):
    return recorded([[1.0, 0.0, 0.0, 0.0]] * frames, lens)


class TestGyroSource:
    """The recorded orientation is used only when all of it is there."""

    CALIBRATION = GYRO_CALIBRATIONS[("HERO10 Black", "S")]

    @pytest.fixture()
    def telemetry(self, monkeypatch):
        by_path = {}
        monkeypatch.setattr(stabilise_module, "read_telemetry", by_path.get)
        return by_path

    def test_every_rush_carrying_it_gives_a_source(self, telemetry, tmp_path):
        a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
        telemetry.update({a: still(100), b: still(50)})

        source = gyro_source([a, b], [100, 50], height=1080, fps=60.0)

        assert source.focal == pytest.approx(self.CALIBRATION.focal_1080)
        assert source.roll == pytest.approx(self.CALIBRATION.roll)

    def test_one_rush_without_it_means_the_picture_is_analysed(
        self, telemetry, tmp_path
    ):
        a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
        telemetry.update({a: still(100)})

        assert gyro_source([a, b], [100, 50], height=1080, fps=60.0) is None

    def test_the_last_chapter_may_lack_its_partial_last_second(
        self, telemetry, tmp_path
    ):
        # A GoPro writes its telemetry by the second and leaves out the last,
        # partial batch: GX081165 has 8686 frames and 8640 orientations.
        a = tmp_path / "a.mp4"
        telemetry.update({a: recorded([turned(1, 0.0)] * 8639 + [turned(1, 2.0)])})

        source = gyro_source([a], [8686], height=1080, fps=59.94)

        assert len(source.orientations[0]) == 8686
        assert np.allclose(source.orientations[0][-46:], source.orientations[0][8639])

    def test_more_than_a_second_missing_is_not_made_up(self, telemetry, tmp_path):
        a = tmp_path / "a.mp4"
        telemetry.update({a: still(8600)})

        assert gyro_source([a], [8686], height=1080, fps=59.94) is None

    def test_a_lens_never_measured_is_left_to_the_analysis(self, telemetry, tmp_path):
        a = tmp_path / "a.mp4"
        telemetry.update({a: still(100, lens="W")})

        assert gyro_source([a], [100], height=1080, fps=60.0) is None

    def test_another_model_does_not_borrow_the_calibration(self, telemetry, tmp_path):
        # The same lens letter on another GoPro need not have the same field.
        a = tmp_path / "a.mp4"
        other = still(100)
        telemetry.update(
            {a: Telemetry("HERO12 Black", other.orientations, other.settings)}
        )

        assert gyro_source([a], [100], height=1080, fps=60.0) is None

    def test_the_focal_length_follows_the_frame_height(self, telemetry, tmp_path):
        a = tmp_path / "a.mp4"
        telemetry.update({a: still(100)})

        source = gyro_source([a], [100], height=2160, fps=60.0)

        assert source.focal == pytest.approx(2 * self.CALIBRATION.focal_1080)


def _lines(path):
    return [
        [float(value) for value in line.split()]
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    ]


class TestGyroTransforms:
    def test_a_steady_drift_across_the_point_is_taken_out(self):
        # The gyroscope's heading drifts while the picture does not move:
        # locking onto one frame would slide the corrected picture sideways.
        orientations = [turned(1, 0.01 * frame) for frame in range(200)]
        source = GyroSource([np.asarray(orientations)], [200], focal=600.0)

        rotations = gyro_rotations(point(0, 200), source)

        assert np.abs(rotations).max() < 1e-6

    def test_the_sway_around_it_is_kept(self):
        sway = [0.5 * math.sin(frame / 5) for frame in range(200)]
        orientations = [
            turned(0, 0.02 * frame + wobble) for frame, wobble in enumerate(sway)
        ]
        source = GyroSource([np.asarray(orientations)], [200], focal=600.0)

        rotations = gyro_rotations(point(0, 200), source)

        # Tipping by the sway, around a course with the drift removed.
        tips = np.degrees(rotations[:, 0])
        assert np.corrcoef(tips, sway)[0, 1] > 0.99
        assert np.ptp(tips) == pytest.approx(np.ptp(sway), rel=0.1)

    def test_the_reference_frame_does_not_move(self, tmp_path):
        path = tmp_path / "p.trf"
        write_gyro_transforms(path, np.zeros((3, 3)), focal=600.0)

        assert _lines(path)[1] == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    def test_a_tip_becomes_a_vertical_shift(self, tmp_path):
        path = tmp_path / "p.trf"
        write_gyro_transforms(path, np.array([[0.01, 0.0, 0.0]]), focal=600.0)

        _, x, y, angle, _, _ = _lines(path)[0]
        assert (x, angle) == (0.0, 0.0)
        assert y == pytest.approx(6.0)

    def test_a_sideways_turn_becomes_a_horizontal_shift(self, tmp_path):
        path = tmp_path / "p.trf"
        write_gyro_transforms(path, np.array([[0.0, 0.01, 0.0]]), focal=600.0)

        _, x, y, angle, _, _ = _lines(path)[0]
        assert (y, angle) == (0.0, 0.0)
        assert x == pytest.approx(-6.0)

    def test_the_roll_is_corrected_by_its_calibrated_share(self, tmp_path):
        path = tmp_path / "p.trf"
        write_gyro_transforms(path, np.array([[0.0, 0.0, 0.02]]), focal=600.0, roll=0.5)

        _, x, y, angle, _, _ = _lines(path)[0]
        assert (x, y) == (0.0, 0.0)
        assert angle == pytest.approx(0.01)

    def test_the_turn_is_read_in_the_camera_s_axes(self):
        # Pointed a quarter turn sideways, then tipped 1° about the sensor's
        # own axis: that must read as a pure tip. The reverse order smears it
        # over the other axes according to where the camera was pointing.
        pointing = np.array([turned(1, 90.0)])
        tipped = multiply(np.array([turned(0, 1.0)]), pointing)
        frames = np.concatenate([pointing, tipped, pointing, tipped, pointing])
        source = GyroSource([frames], [5], 600.0)

        rotations = gyro_rotations(point(0, 5), source)

        assert math.degrees(rotations[1, 0] - rotations[0, 0]) == pytest.approx(
            1.0, abs=1e-6
        )
        assert rotations[:, 1:] == pytest.approx(np.zeros((5, 2)), abs=1e-9)

    def test_a_point_across_two_rushes_reads_both(self):
        first = recorded([turned(1, 1.0)] * 10)
        second = recorded([turned(1, 5.0)] * 10)
        source = GyroSource(
            [first.orientations, second.orientations], [10, 10], focal=600.0
        )

        rotations = gyro_rotations(point(6, 14), source)

        # Eight frames, four from each rush: the 4° step between the two
        # rushes sits at the join. Taking the trend out tilts every step by
        # the same amount, so the step stands 4° above all the others.
        assert len(rotations) == 8
        steps = np.degrees(np.diff(rotations[:, 1]))
        others = np.delete(steps, 3)
        assert others == pytest.approx(np.full(6, others[0]), abs=1e-9)
        assert steps[3] - others[0] == pytest.approx(4.0)

    def test_each_kept_point_gets_its_file_where_the_render_reads(self, tmp_path):
        source = GyroSource([still(1000).orientations], [1000], focal=600.0, roll=0.5)
        points = [point(0, 100), point(200, 200), point(300, 350)]
        directory = tmp_path / "stabilise"
        directory.mkdir()

        write_gyro_paths(points, directory, source)

        assert sorted(path.name for path in directory.glob("*.trf")) == [
            "point_000.trf",
            "point_001.trf",
        ]
        assert wrote_from_gyro(directory)
        assert len(_lines(directory / "point_001.trf")) == 50

    def test_vidstab_reads_what_is_written(self, tmp_path):
        # The text format is vid.stab's own; this runs ffmpeg to be sure a
        # file written here is taken, not rejected as unparsable.
        clip = tmp_path / "clip.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=96x54:rate=25:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        path = tmp_path / "point_000.trf"
        rotations = np.array([[0.0, 0.01 * i, 0.001 * i] for i in range(25)])
        write_gyro_transforms(path, rotations, focal=600.0)

        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                "-vf", transform_filter(path, StabiliseSettings()),
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )  # fmt: skip

        assert result.returncode == 0, result.stderr


class TestWhichCorrection:
    """The render applies the correction that suits where the paths came from."""

    POINTS: ClassVar[list[dict]] = [point(0, 100), point(200, 300)]

    def test_the_gyroscope_leaves_its_marker(self, tmp_path):
        source = GyroSource([still(1000).orientations], [1000], focal=600.0)

        write_gyro_paths(self.POINTS, tmp_path, source)

        assert wrote_from_gyro(tmp_path)

    def test_an_analysis_directory_carries_no_marker(self, tmp_path):
        assert not wrote_from_gyro(tmp_path)

    def test_the_gyroscope_s_corrections_are_applied_as_a_tripod(self, tmp_path):
        filters = transform_filters(self.POINTS, tmp_path, fps=25.0, from_gyro=True)

        assert all(":tripod=1:" in text for text in filters)

    def test_the_picture_s_paths_are_smoothed(self, tmp_path):
        filters = transform_filters(self.POINTS, tmp_path, fps=25.0, from_gyro=False)

        assert all(":relative=1:" in text for text in filters)
        assert len(filters) == 2


class TestRelativeRoundTrip:
    def test_a_path_measured_in_the_picture_is_applied_by_ffmpeg(self, tmp_path):
        # The fallback end to end, with ffmpeg itself: analysis, then the
        # relative correction reading what the analysis wrote.
        clip = tmp_path / "clip.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=2",
                "-vf", "crop=w=150:h=84:x='5+4*sin(t*9)':y='3+3*cos(t*7)'",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        path = tmp_path / "point_000.trf"
        settings = StabiliseSettings()

        analysis = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                "-vf", detect_filter(path, settings), "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )  # fmt: skip
        correction = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                "-vf", relative_transform_filter(path, 25.0, settings),
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )  # fmt: skip

        assert analysis.returncode == 0, analysis.stderr
        assert correction.returncode == 0, correction.stderr
