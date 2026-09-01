"""Tests for core.models.render_queue.ffmpeg.

Subprocess/ffmpeg/ffprobe calls are always mocked here: `_execute()` and
`build_command()` are tested by mocking at the module boundaries
(`Game.get_source_files`, `get_fps`, `_is_cuda_available`, `_run_subprocess`,
`_probe_file`) rather than shelling out to a real ffmpeg binary.
"""

from __future__ import annotations

from pathlib import Path

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

        def fake_build_command(self, chapter_metadata_tmp_path=None, output_file=None):
            output_file.write_bytes(rendered_bytes)
            return ["true"]

        monkeypatch.setattr(RenderQueueItemProxy, "build_command", fake_build_command)
        monkeypatch.setattr(item, "_run_subprocess", lambda command: None)
        monkeypatch.setattr(item, "_probe_file", lambda path: VALID_METADATA)

        item._execute()

        assert item.final_output_path.read_bytes() == rendered_bytes

    def test_validation_failure_raises_and_does_not_move_file(self, game, monkeypatch):
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="low")

        def fake_build_command(self, chapter_metadata_tmp_path=None, output_file=None):
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

        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.set_json({"points": [{"in": 0, "out": 25}], "overlays": []})

        item = baker.make("core.RenderQueueItemCut", cut=cut, preset="medium")
        output_file = tmp_path / "out.mp4"

        cmd = item.build_command(output_file=output_file)

        assert cmd[0] == "ffmpeg"
        assert "-filter_complex" in cmd
        assert str(output_file.absolute()) in cmd


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
