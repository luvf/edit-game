"""Tests for core.models.render_queue.ffmpeg.

Subprocess/ffmpeg/ffprobe calls are always mocked here: `_execute()` and
`build_command()` are tested by mocking at the module boundaries
(`Game.get_source_files`, `get_fps`, `_is_cuda_available`, `_run_subprocess`,
`_probe_file`) rather than shelling out to a real ffmpeg binary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from model_bakery import baker

from core.models.cut import Cut
from core.models.game import Game
from core.models.render_queue.ffmpeg import (
    RenderQueueItemArchive,
    RenderQueueItemFFMPEG,
    RenderQueueItemProxy,
)

if TYPE_CHECKING:
    from pathlib import Path

VALID_METADATA = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.5"},
    "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
}


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
