"""Tests for core.models.render_queue.ffmpeg.

Subprocess/ffmpeg/ffprobe calls are always mocked here: `_execute()` and
`build_command()` are tested by mocking at the module boundaries
(`Game.get_source_files`, `get_fps`, `_is_cuda_available`, `_run_subprocess`,
`_probe_file`) rather than shelling out to a real ffmpeg binary.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from model_bakery import baker

from core.models.cut import Cut
from core.models.game import Game
from core.models.render_queue import ffmpeg as ffmpeg_module
from core.models.render_queue.ffmpeg import (
    RenderQueueItemArchive,
    RenderQueueItemFFMPEG,
    RenderQueueItemProxy,
)
from jugger_video_manipulation.gopro_telemetry import Settings, Telemetry
from jugger_video_manipulation.stabilise import GYRO_MARKER, GyroSource

VALID_METADATA = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.5"},
    "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
}


class TestIsCudaAvailable:
    """CUDA availability must be probed, not read off the build flags."""

    @pytest.fixture(autouse=True)
    def _clear_probe_cache(self):
        ffmpeg_module._cuda_device_initialises.cache_clear()
        yield
        ffmpeg_module._cuda_device_initialises.cache_clear()

    @pytest.fixture()
    def probe(self, monkeypatch):
        """Capture the probe argv and control its exit code."""
        calls: list[list[str]] = []

        class _Result:
            returncode = 0

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            result = _Result()
            result.returncode = fake_run.returncode
            return result

        fake_run.returncode = 0
        monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)
        return fake_run, calls

    def test_probe_creates_a_cuda_device(self, probe):
        """A build-flag listing would pass a bare boolean test; this won't."""
        _, calls = probe

        assert RenderQueueItemFFMPEG._is_cuda_available() is True
        assert "-init_hw_device" in calls[0]
        assert "cuda:0" in calls[0]

    def test_unusable_driver_reports_unavailable(self, probe):
        """A driver/library mismatch exits non-zero; we must fall back to CPU."""
        fake_run, _ = probe
        fake_run.returncode = 187

        assert RenderQueueItemFFMPEG._is_cuda_available() is False

    def test_missing_ffmpeg_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda _: None)

        assert RenderQueueItemFFMPEG._is_cuda_available() is False

    def test_probe_failure_reports_unavailable(self, monkeypatch):
        def _boom(*_a, **_k):
            raise OSError("ffmpeg blew up")

        monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        monkeypatch.setattr(ffmpeg_module.subprocess, "run", _boom)

        assert RenderQueueItemFFMPEG._is_cuda_available() is False

    def test_result_is_cached(self, probe):
        fake_run, calls = probe

        RenderQueueItemFFMPEG._is_cuda_available()
        RenderQueueItemFFMPEG._is_cuda_available()

        assert len(calls) == 1


class TestPresetArgs:
    def test_uses_cpu_args_when_cuda_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        item = RenderQueueItemFFMPEG(preset="medium")
        assert item._preset_args() == RenderQueueItemFFMPEG.PRESET_ARGS_CPU["medium"]

    def test_uses_gpu_args_when_cuda_available(self, monkeypatch):
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: True)
        )
        item = RenderQueueItemFFMPEG(preset="medium")
        assert item._preset_args() == RenderQueueItemFFMPEG.PRESET_ARGS_GPU["medium"]

    def test_unknown_preset_falls_back_to_default_cpu(self, monkeypatch):
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        item = RenderQueueItemFFMPEG(preset="unknown")
        default_key = next(iter(RenderQueueItemFFMPEG.PRESET_ARGS_CPU))
        assert item._preset_args() == RenderQueueItemFFMPEG.PRESET_ARGS_CPU[default_key]

    def test_archive_preset_args_are_always_cpu(self, game, monkeypatch):
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: True)
        )
        item = baker.make("core.RenderQueueItemArchive", game=game)
        assert item._preset_args() == RenderQueueItemArchive.PRESET_ARGS_CPU["archive"]


class TestArchiveDownscale:
    """Archives are normalised to 1080p; taller sources are downscaled."""

    @staticmethod
    def _crf(preset_args) -> str:
        video_args = preset_args["video"]
        return video_args[video_args.index("-crf") + 1]

    @pytest.fixture()
    def item(self, game):
        return baker.make("core.RenderQueueItemArchive", game=game)

    @pytest.fixture()
    def heights(self, monkeypatch):
        """Stub ffprobe: map a source path to the height it reports."""
        by_path: dict[str, int | None] = {}
        monkeypatch.setattr(
            RenderQueueItemArchive,
            "_source_video_height",
            classmethod(lambda cls, path: by_path.get(str(path))),
        )
        return by_path

    @pytest.mark.parametrize("height", [2160, 1440, 1081], ids=str)
    def test_taller_source_is_downscaled_to_1080p(self, item, heights, height):
        heights["/rush.mp4"] = height
        args = item._preset_args([Path("/rush.mp4")])

        assert args["scale"] == ["-2", "1080"]
        assert self._crf(args) == "34"

    @pytest.mark.parametrize("height", [1080, 720], ids=str)
    def test_source_at_or_below_1080p_is_left_alone(self, item, heights, height):
        heights["/rush.mp4"] = height
        args = item._preset_args([Path("/rush.mp4")])

        assert "scale" not in args
        assert self._crf(args) == "28"

    def test_tallest_source_decides(self, item, heights):
        heights.update({"/a.mp4": 1080, "/b.mp4": 2160})
        args = item._preset_args([Path("/a.mp4"), Path("/b.mp4")])

        assert args["scale"] == ["-2", "1080"]
        assert self._crf(args) == "34"

    def test_unreadable_source_keeps_preset_args(self, item, heights):
        heights["/broken.mp4"] = None
        args = item._preset_args([Path("/broken.mp4")])

        assert "scale" not in args
        assert self._crf(args) == "28"

    def test_no_source_keeps_preset_args(self, item):
        args = item._preset_args([])

        assert "scale" not in args
        assert self._crf(args) == "28"

    def test_class_level_preset_is_not_mutated(self, item, heights):
        heights["/rush.mp4"] = 2160
        args = item._preset_args([Path("/rush.mp4")])
        base = RenderQueueItemArchive.PRESET_ARGS_CPU["archive"]

        assert args["audio"] == base["audio"]
        assert "scale" not in base
        assert self._crf(base) == "28"

    def test_downscale_reaches_the_ffmpeg_command(self, item, heights, monkeypatch):
        """The scale key must actually land in the filter_complex."""
        heights["/rush.mp4"] = 2160
        monkeypatch.setattr(
            RenderQueueItemArchive,
            "get_source_files",
            lambda self: [Path("/rush.mp4")],
        )
        monkeypatch.setattr(
            RenderQueueItemArchive, "_is_cuda_available", staticmethod(lambda: False)
        )

        cmd = item.build_command(output_file=Path("/tmp/out.mp4"))
        filter_complex = cmd[cmd.index("-filter_complex") + 1]

        assert "scale=-2:1080" in filter_complex
        assert cmd[cmd.index("-crf") + 1] == "34"


class TestValidationErrors:
    def test_no_errors_for_valid_metadata(self):
        item = RenderQueueItemFFMPEG()
        assert item._validation_errors(VALID_METADATA) == []

    def test_reports_all_issues(self):
        item = RenderQueueItemFFMPEG()
        errors = item._validation_errors(
            {"format": {"format_name": "avi", "duration": "2"}, "streams": []}
        )
        assert any("mp4" in e for e in errors)
        assert any("5s" in e for e in errors)
        assert any("vidéo" in e for e in errors)
        assert any("audio" in e for e in errors)

    def test_missing_duration_defaults_to_zero(self):
        item = RenderQueueItemFFMPEG()
        errors = item._validation_errors(
            {
                "format": {"format_name": "mp4"},
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            }
        )
        assert any("5s" in e for e in errors)


class TestMoveIntoPlace:
    def test_moves_new_file_into_place(self, tmp_path: Path):
        tmp_file = tmp_path / "src.mp4"
        tmp_file.write_bytes(b"new-content")
        final_path = tmp_path / "dest" / "out.mp4"
        final_path.parent.mkdir()

        RenderQueueItemFFMPEG._move_into_place(tmp_file, final_path)

        assert final_path.read_bytes() == b"new-content"
        assert list(final_path.parent.iterdir()) == [final_path]

    def test_replaces_existing_file_atomically(self, tmp_path: Path):
        tmp_file = tmp_path / "src.mp4"
        tmp_file.write_bytes(b"new-content")
        final_path = tmp_path / "out.mp4"
        final_path.write_bytes(b"old-content")

        RenderQueueItemFFMPEG._move_into_place(tmp_file, final_path)

        assert final_path.read_bytes() == b"new-content"

    def test_old_file_survives_if_copy_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        tmp_file = tmp_path / "src.mp4"
        tmp_file.write_bytes(b"new-content")
        final_path = tmp_path / "out.mp4"
        final_path.write_bytes(b"old-content")

        def _boom(*_a, **_k):
            raise OSError("simulated copy failure")

        monkeypatch.setattr("shutil.copyfile", _boom)

        with pytest.raises(OSError, match="simulated copy failure"):
            RenderQueueItemFFMPEG._move_into_place(tmp_file, final_path)

        assert final_path.read_bytes() == b"old-content"


class TestExecute:
    def test_happy_path_moves_rendered_file_into_final_path(self, game, monkeypatch):
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="low")
        rendered_bytes = b"rendered-bytes"

        def fake_build_command(
            self, chapter_metadata_tmp_path=None, output_file=None, overlay_dir=None
        ):
            output_file.write_bytes(rendered_bytes)
            return ["true"]

        monkeypatch.setattr(RenderQueueItemProxy, "build_command", fake_build_command)
        monkeypatch.setattr(item, "_run_subprocess", lambda command: None)
        monkeypatch.setattr(item, "_probe_file", lambda path: VALID_METADATA)

        item._execute()

        assert item.final_output_path.read_bytes() == rendered_bytes

    def test_validation_failure_raises_and_does_not_move_file(self, game, monkeypatch):
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="low")

        def fake_build_command(
            self, chapter_metadata_tmp_path=None, output_file=None, overlay_dir=None
        ):
            output_file.write_bytes(b"bad-render")
            return ["true"]

        monkeypatch.setattr(RenderQueueItemProxy, "build_command", fake_build_command)
        monkeypatch.setattr(item, "_run_subprocess", lambda command: None)
        monkeypatch.setattr(
            item,
            "_probe_file",
            lambda path: {"format": {"format_name": "avi"}, "streams": []},
        )

        with pytest.raises(ValueError, match="Validation errors"):
            item._execute()

        assert not item.final_output_path.exists()


class TestStabilise:
    """A cut can ask for each kept point to be steadied."""

    @pytest.fixture()
    def sources(self, game, monkeypatch, tmp_path):
        files = [tmp_path / "a.mp4"]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.get_fps", lambda video_file: 25.0
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda sources: [100_000 for _ in sources],
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.gyro_source", lambda *args: None
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG,
            "_source_video_height",
            classmethod(lambda cls, path: 1080),
        )
        return files

    @staticmethod
    def _item(game, *, stabilise):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.set_json(
            {
                "points": [{"in": 0, "out": 250}, {"in": 1000, "out": 1250}],
                "overlays": [],
                "display": {"stabilise": stabilise},
            }
        )
        return baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")

    def test_each_kept_point_is_corrected_in_the_render(self, game, sources, tmp_path):
        item = self._item(game, stabilise=True)

        cmd = item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

        graph = cmd[cmd.index("-filter_complex") + 1]
        assert graph.count("vidstabtransform=") == 2
        assert str(tmp_path / "work" / "stabilise" / "point_001.trf") in graph

    def test_paths_measured_in_the_picture_are_smoothed(self, game, sources, tmp_path):
        item = self._item(game, stabilise=True)

        cmd = item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

        graph = cmd[cmd.index("-filter_complex") + 1]
        assert graph.count(":relative=1:") == 2
        assert ":tripod=1:" not in graph

    def test_the_gyroscope_s_corrections_are_applied_as_a_tripod(
        self, game, sources, tmp_path
    ):
        item = self._item(game, stabilise=True)
        directory = tmp_path / "work" / "stabilise"
        directory.mkdir(parents=True)
        (directory / GYRO_MARKER).write_text("orientation enregistrée\n")

        cmd = item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

        graph = cmd[cmd.index("-filter_complex") + 1]
        assert graph.count(":tripod=1:") == 2
        assert ":relative=1:" not in graph

    def test_the_correction_comes_before_the_crossfade(self, game, sources, tmp_path):
        # Steadying the dissolve instead would read a camera path the blend
        # of two shots does not have.
        item = self._item(game, stabilise=True)

        cmd = item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

        graph = cmd[cmd.index("-filter_complex") + 1]
        assert graph.index("vidstabtransform") < graph.index("xfade")

    def test_nothing_is_corrected_unless_the_cut_asks(self, game, sources, tmp_path):
        item = self._item(game, stabilise=False)

        cmd = item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

        assert "vidstab" not in cmd[cmd.index("-filter_complex") + 1]

    def test_a_preview_shows_the_command_without_it(self, game, sources, tmp_path):
        # A preview writes nothing, so there is no camera path to read.
        item = self._item(game, stabilise=True)

        cmd = item.build_command(output_file=tmp_path / "out.mp4")

        assert "vidstab" not in cmd[cmd.index("-filter_complex") + 1]

    def test_the_analysis_runs_before_the_render(
        self, game, sources, tmp_path, monkeypatch
    ):
        item = self._item(game, stabilise=True)
        ran = []
        monkeypatch.setattr(item, "_run_subprocess", ran.append)

        item._before_render(tmp_path / "work")

        assert len(ran) == 1
        graph = ran[0][ran[0].index("-filter_complex") + 1]
        assert graph.count("vidstabdetect=") == 2
        assert ran[0][-3:] == ["-f", "null", "-"]
        assert (tmp_path / "work" / "stabilise").is_dir()

    def test_the_recorded_orientation_replaces_the_analysis(
        self, game, sources, tmp_path, monkeypatch
    ):
        item = self._item(game, stabilise=True)
        still = Telemetry(
            camera="HERO10 Black",
            orientations=np.tile([1.0, 0.0, 0.0, 0.0], (100_000, 1)),
            settings=Settings(lens="S"),
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.gyro_source",
            lambda files, counts, height, fps: GyroSource(
                [still.orientations], counts, 600.0
            ),
        )
        ran = []
        monkeypatch.setattr(item, "_run_subprocess", ran.append)

        item._before_render(tmp_path / "work")

        assert ran == []
        directory = tmp_path / "work" / "stabilise"
        written = sorted(directory.glob("*.trf"))
        assert [path.name for path in written] == ["point_000.trf", "point_001.trf"]
        # The render will apply these as a tripod, not smooth them.
        assert (directory / GYRO_MARKER).exists()

    def test_an_archived_game_reads_the_orientation_from_its_rushes(
        self, game, sources, tmp_path, monkeypatch
    ):
        rushes = [tmp_path / "GX01.MP4", tmp_path / "GX02.MP4"]
        for rush in rushes:
            rush.write_bytes(b"rush")
        archive = sources
        monkeypatch.setattr(
            Game,
            "get_source_files",
            lambda self, force_rush=False: rushes if force_rush else archive,
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda files: [60_000, 40_000] if files == rushes else [100_000],
        )
        asked = []

        def recorded_only_in_rushes(files, counts, height, fps):
            asked.append(files)
            return GyroSource([], counts, 600.0) if files == rushes else None

        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.gyro_source", recorded_only_in_rushes
        )

        gyro = self._item(game, stabilise=True)._gyro_source(archive, [100_000], 25.0)

        assert asked == [archive, rushes]
        assert gyro.frame_counts == [60_000, 40_000]

    def test_rushes_that_do_not_match_the_archive_are_not_trusted(
        self, game, sources, tmp_path, monkeypatch
    ):
        # Other frames than the archive's would put every correction on the
        # wrong frame: the picture is analysed instead.
        rushes = [tmp_path / "GX01.MP4"]
        rushes[0].write_bytes(b"rush")
        archive = sources
        monkeypatch.setattr(
            Game,
            "get_source_files",
            lambda self, force_rush=False: rushes if force_rush else archive,
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda files: [99_000] if files == rushes else [100_000],
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.gyro_source",
            lambda files, counts, height, fps: (
                GyroSource([], counts, 600.0) if files == rushes else None
            ),
        )

        item = self._item(game, stabilise=True)

        assert item._gyro_source(archive, [100_000], 25.0) is None

    def test_no_analysis_unless_the_cut_asks(
        self, game, sources, tmp_path, monkeypatch
    ):
        item = self._item(game, stabilise=False)
        ran = []
        monkeypatch.setattr(item, "_run_subprocess", ran.append)

        item._before_render(tmp_path / "work")

        assert ran == []

    def test_the_work_directory_is_removed_after_the_render(
        self, game, monkeypatch, tmp_path
    ):
        # Camera paths run to megabytes per minute of footage.
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="low")
        seen = []

        def fake_build_command(
            self, chapter_metadata_tmp_path=None, output_file=None, overlay_dir=None
        ):
            overlay_dir.mkdir(parents=True)
            (overlay_dir / "point_000.trf").write_bytes(b"path")
            seen.append(overlay_dir)
            output_file.write_bytes(b"rendered")
            return ["true"]

        monkeypatch.setattr(RenderQueueItemProxy, "build_command", fake_build_command)
        monkeypatch.setattr(item, "_run_subprocess", lambda command: None)
        monkeypatch.setattr(item, "_probe_file", lambda path: VALID_METADATA)

        item._execute()

        assert seen
        assert not seen[0].exists()


class TestTail:
    """A cut render keeps running for 25 s once the last point is over."""

    @pytest.fixture()
    def item(self, game, monkeypatch):
        files = [Path("/rushes/a.mp4")]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.get_fps", lambda video_file: 25.0
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.gyro_source", lambda *args: None
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG,
            "_source_video_height",
            classmethod(lambda cls, path: 1080),
        )
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.set_json(
            {
                "points": [{"in": 0, "out": 250}, {"in": 1000, "out": 1250}],
                "overlays": [],
            }
        )
        return baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")

    @staticmethod
    def _rushes_hold(monkeypatch, frames):
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda sources: [frames],
        )

    @staticmethod
    def _graph(item, tmp_path):
        cmd = item.build_command(output_file=tmp_path / "out.mp4")
        return cmd[cmd.index("-filter_complex") + 1]

    def test_the_last_point_runs_on_for_25_seconds(self, item, monkeypatch, tmp_path):
        self._rushes_hold(monkeypatch, 100_000)

        # 1250 + 25 s at 25 fps = 1875, bounds half a frame back.
        assert "trim=start=39.980000:end=74.980000" in self._graph(item, tmp_path)

    def test_a_match_filmed_to_its_end_gives_what_is_left(
        self, item, monkeypatch, tmp_path
    ):
        self._rushes_hold(monkeypatch, 1400)

        assert "trim=start=39.980000:end=55.980000" in self._graph(item, tmp_path)

    def test_unreadable_rushes_still_ask_for_the_whole_tail(
        self, item, monkeypatch, tmp_path
    ):
        def unreadable(sources):
            raise ValueError("illisible")

        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts", unreadable
        )

        assert "end=74.980000" in self._graph(item, tmp_path)

    def test_the_end_screen_can_be_turned_off(self, item, monkeypatch, tmp_path):
        self._rushes_hold(monkeypatch, 100_000)
        item.cut.set_json(
            {
                "points": [{"in": 0, "out": 250}, {"in": 1000, "out": 1250}],
                "overlays": [],
                "display": {"tail": False},
            }
        )

        assert "trim=start=39.980000:end=49.980000" in self._graph(item, tmp_path)

    def test_only_the_last_point_is_extended(self, item, monkeypatch, tmp_path):
        self._rushes_hold(monkeypatch, 100_000)

        assert "trim=start=0.000000:end=9.980000" in self._graph(item, tmp_path)

    def test_the_last_chapter_runs_to_the_end_of_the_tail(
        self, item, monkeypatch, tmp_path
    ):
        self._rushes_hold(monkeypatch, 100_000)
        metadata = tmp_path / "chapters.txt"

        item.build_command(
            chapter_metadata_tmp_path=metadata, output_file=tmp_path / "out.mp4"
        )

        # 10 s, then 35 s starting one crossfade early: 9 + 35 = 44 s.
        assert "START=9000\nEND=44000" in metadata.read_text()

    def test_the_tail_is_stabilised_with_its_point(self, item, monkeypatch, tmp_path):
        self._rushes_hold(monkeypatch, 100_000)
        item.cut.set_json(
            {
                "points": [{"in": 0, "out": 250}, {"in": 1000, "out": 1250}],
                "overlays": [],
                "display": {"stabilise": True},
            }
        )
        ran = []
        monkeypatch.setattr(item, "_run_subprocess", ran.append)

        item._before_render(tmp_path / "work")

        graph = ran[0][ran[0].index("-filter_complex") + 1]
        assert re.findall(r"end_frame=(\d+)", graph) == ["250", "875"]


class TestIntroInTheRender:
    """A cut with a card plays the footage before its first point behind it."""

    @pytest.fixture()
    def item(self, game, monkeypatch):
        files = [Path("/rushes/a.mp4")]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.get_fps", lambda video_file: 25.0
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda sources: [100_000 for _ in sources],
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.RenderQueueItemCut._render_size",
            lambda self, source, scale: (640, 360),
        )
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        return baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")

    @staticmethod
    def _command(item, tmp_path, **card):
        item.cut.set_json(
            {
                "points": [{"in": 1000, "out": 1250, "point": "left"}],
                "overlays": [{"type": "GameInfo", "team1": "A", "team2": "B"}],
                "display": {"title_card": card} if card else {},
            }
        )
        return item.build_command(
            output_file=tmp_path / "out.mp4", overlay_dir=tmp_path / "work"
        )

    def test_the_card_plays_over_the_footage_with_its_sound(self, item, tmp_path):
        cmd = self._command(item, tmp_path)
        graph = cmd[cmd.index("-filter_complex") + 1]

        assert "gblur=" in graph
        assert "volume=0.25" in graph
        # The footage brings its own sound: no silent input any more.
        assert not any("anullsrc" in arg for arg in cmd)

    def test_a_flat_card_still_stands_on_silence(self, item, tmp_path):
        cmd = self._command(item, tmp_path, background="flat")
        graph = cmd[cmd.index("-filter_complex") + 1]

        assert "gblur=" not in graph
        assert any("anullsrc" in arg for arg in cmd)


class TestBuildCommandProxy:
    def test_includes_preset_codec_and_all_inputs(self, game, monkeypatch, tmp_path):
        source_files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: source_files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="medium")
        output_file = tmp_path / "out.mp4"

        cmd = item.build_command(output_file=output_file)

        assert cmd[0] == "ffmpeg"
        assert cmd.count("-i") == 2
        for token in RenderQueueItemFFMPEG.PRESET_ARGS_CPU["medium"]["video"]:
            assert token in cmd
        assert str(output_file.absolute()) in cmd


class TestBuildCommandCut:
    def test_includes_filter_complex_and_output(self, game, monkeypatch, tmp_path):
        source_files = [tmp_path / "a.mp4"]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: source_files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.get_fps", lambda video_file: 25.0
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda sources: [100_000 for _ in sources],
        )

        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.set_json({"points": [{"in": 0, "out": 25}], "overlays": []})

        item = baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")
        output_file = tmp_path / "out.mp4"

        cmd = item.build_command(output_file=output_file)

        assert cmd[0] == "ffmpeg"
        assert "-filter_complex" in cmd
        assert str(output_file.absolute()) in cmd

    def test_maps_a_video_output_pinned_to_the_frame_rate(
        self, game, monkeypatch, tmp_path
    ):
        """The mapped video pad must be the graph's `fps` node.

        Without it the output stream carries no frame rate, and NVENC sizes
        its constant-quality target from that rate: a `-cq 18` render then
        comes out around 2 Mbit/s, artefacts and all, whatever the preset
        asks for.
        """
        source_files = [tmp_path / "a.mp4"]
        monkeypatch.setattr(
            Game, "get_source_files", lambda self, force_rush=False: source_files
        )
        monkeypatch.setattr(
            RenderQueueItemFFMPEG, "_is_cuda_available", staticmethod(lambda: False)
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.get_fps", lambda video_file: 25.0
        )
        monkeypatch.setattr(
            "core.models.render_queue.ffmpeg.probe_frame_counts",
            lambda sources: [100_000 for _ in sources],
        )

        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.set_json({"points": [{"in": 0, "out": 25}], "overlays": []})

        item = baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")

        cmd = item.build_command(output_file=tmp_path / "out.mp4")

        graph = cmd[cmd.index("-filter_complex") + 1]
        mapped = cmd[cmd.index("-map") + 1]

        assert "fps=25" in graph
        assert graph.endswith(mapped)
        assert mapped.startswith("[fps_v")


class TestArchiveGetSourceFiles:
    def test_delegates_with_force_rush(self, game, monkeypatch):
        calls = []

        def fake(self, *, force_rush=False):
            calls.append(force_rush)
            return ["dummy"]

        monkeypatch.setattr(Game, "get_source_files", fake)
        item = baker.make("core.RenderQueueItemArchive", game=game)

        assert item.get_source_files() == ["dummy"]
        assert calls == [True]


class TestProbeVideoStreamEntry:
    """The ffprobe parsing itself, which the downscale tests stub away.

    A GoPro MP4 exposes two groups of streams, so `-select_streams v:0` matches
    twice and ffprobe prints the value once per match. Reading the whole output
    gave the height twice over, `int()` refused it, the height came back unknown
    downscale was silently skipped — which is how 4K archives stayed at 40 GB
    an hour.
    """

    @staticmethod
    def _stub(monkeypatch, stdout: str, returncode: int = 0):
        import subprocess

        # The probe is cached on (path, entry); tests reuse both, so the cache
        # has to go or the second test would read the first one's answer.
        RenderQueueItemFFMPEG._probe_video_stream_entry.cache_clear()

        def fake_run(*_args, **_kwargs):
            if returncode:
                raise subprocess.CalledProcessError(returncode, "ffprobe")
            return subprocess.CompletedProcess(
                args=["ffprobe"], returncode=0, stdout=stdout, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_reads_a_single_value(self, monkeypatch):
        self._stub(monkeypatch, "1080\n")

        assert (
            RenderQueueItemFFMPEG._probe_video_stream_entry(Path("/a.mp4"), "height")
            == "1080"
        )

    def test_keeps_only_the_first_of_a_gopro_double_listing(self, monkeypatch):
        self._stub(monkeypatch, "2160\n2160\n")

        assert (
            RenderQueueItemFFMPEG._probe_video_stream_entry(Path("/a.mp4"), "height")
            == "2160"
        )

    def test_skips_leading_blank_lines(self, monkeypatch):
        self._stub(monkeypatch, "\n\nhevc\nhevc\n")

        assert (
            RenderQueueItemFFMPEG._probe_video_stream_entry(
                Path("/a.mp4"), "codec_name"
            )
            == "hevc"
        )

    def test_empty_output_is_none(self, monkeypatch):
        self._stub(monkeypatch, "\n \n")

        assert (
            RenderQueueItemFFMPEG._probe_video_stream_entry(Path("/a.mp4"), "height")
            is None
        )

    def test_a_failing_probe_is_none(self, monkeypatch):
        self._stub(monkeypatch, "", returncode=1)

        assert (
            RenderQueueItemFFMPEG._probe_video_stream_entry(Path("/a.mp4"), "height")
            is None
        )


class TestSourceVideoHeightParsing:
    """The height must survive a GoPro's doubled ffprobe output."""

    @staticmethod
    def _stub_probe(monkeypatch, value: str | None):
        monkeypatch.setattr(
            RenderQueueItemFFMPEG,
            "_probe_video_stream_entry",
            staticmethod(lambda path, entry: value),
        )

    def test_a_doubled_listing_yields_a_height(self, monkeypatch):
        # What the probe returns after keeping the first line.
        self._stub_probe(monkeypatch, "2160")

        assert RenderQueueItemArchive._source_video_height(Path("/a.mp4")) == 2160

    def test_a_non_numeric_value_is_none(self, monkeypatch):
        self._stub_probe(monkeypatch, "2160\n2160")

        assert RenderQueueItemArchive._source_video_height(Path("/a.mp4")) is None

    def test_a_missing_value_is_none(self, monkeypatch):
        self._stub_probe(monkeypatch, None)

        assert RenderQueueItemArchive._source_video_height(Path("/a.mp4")) is None

    def test_a_4k_gopro_triggers_the_downscale(self, monkeypatch, game):
        self._stub_probe(monkeypatch, "2160")
        item = baker.make("core.RenderQueueItemArchive", game=game)

        args = item._preset_args([Path("/GX010837.MP4")])

        assert args["scale"] == ["-2", "1080"]
        assert args["video"][args["video"].index("-crf") + 1] == "34"


class TestCommandPreview:
    """A pending item must show the command it will actually run."""

    @pytest.fixture()
    def pending(self, game, monkeypatch):
        monkeypatch.setattr(
            RenderQueueItemArchive,
            "_source_video_height",
            classmethod(lambda cls, path: 2160),
        )
        item = baker.make(
            "core.RenderQueueItemArchive",
            game=game,
            command="ffmpeg -stale-command",
            output_filename="out.mp4",
        )
        item.status = item.Status.CREATED
        return item

    def test_a_pending_item_rebuilds_rather_than_show_a_stale_command(
        self, pending, monkeypatch
    ):
        monkeypatch.setattr(
            RenderQueueItemArchive,
            "build_command",
            lambda self, **_kwargs: ["ffmpeg", "scale=-2:1080"],
        )

        assert "stale" not in pending.command_parameters
        assert "scale=-2:1080" in pending.command_parameters

    def test_a_finished_item_shows_what_it_ran(self, pending):
        pending.status = pending.Status.DONE

        assert pending.command_parameters == "ffmpeg -stale-command"

    def test_a_running_item_shows_what_it_is_running(self, pending):
        pending.status = pending.Status.RUNNING

        assert pending.command_parameters == "ffmpeg -stale-command"

    def test_an_unbuildable_preview_falls_back_to_the_stored_command(
        self, pending, monkeypatch
    ):
        def boom(self, **_kwargs):
            raise RuntimeError("sources absentes")

        monkeypatch.setattr(RenderQueueItemArchive, "build_command", boom)

        assert pending.command_parameters == "ffmpeg -stale-command"

    def test_the_preview_does_not_create_video_file_rows(self, pending, monkeypatch):
        from core.models.video import VideoFile

        monkeypatch.setattr(
            RenderQueueItemArchive,
            "build_command",
            lambda self, **kwargs: ["ffmpeg", str(kwargs.get("output_file"))],
        )
        before = VideoFile.objects.count()

        assert pending.command_parameters
        assert VideoFile.objects.count() == before
