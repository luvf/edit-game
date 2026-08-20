"""Tests for jugger_video_manipulation.ffmpeg_utils."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jugger_video_manipulation.ffmpeg_utils import (
    FilterComplexBuilder,
    _add_input_files,
    _validate_encode_cuda_usage,
    ffmpeg_command_builder,
    get_chapters,
    get_fps,
    write_chapters_metadata,
)


class TestFilterComplexBuilder:
    def test_create_inputs(self):
        builder = FilterComplexBuilder(3)
        assert builder.inputs_v == ["[0:v:0]", "[1:v:0]", "[2:v:0]"]
        assert builder.inputs_a == ["[0:a:0]", "[1:a:0]", "[2:a:0]"]

    def test_filter_concat_single_input_uses_copy(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        assert builder.out_v == "[cv0]"
        assert builder.out_a == "[ca0]"
        assert builder.filter_complex == [
            "[0:v:0]copy[cv0]",
            "[0:a:0]anull[ca0]",
        ]

    def test_filter_concat_multiple_inputs_uses_concat(self):
        builder = FilterComplexBuilder(2)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        assert builder.filter_complex == [
            "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[cv0][ca0]"
        ]

    def test_filter_concat_rejects_mismatched_lengths(self):
        builder = FilterComplexBuilder(2)
        with pytest.raises(ValueError, match="audio and on video"):
            builder.filter_concat(["[0:v:0]"], [])

    def test_filter_concat_rejects_empty_inputs(self):
        builder = FilterComplexBuilder(0)
        with pytest.raises(ValueError, match="greater than 0"):
            builder.filter_concat([], [])

    def test_filter_cut_produces_trim_segments(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        builder.filter_cut(fps=25, points=[{"in": 0, "out": 25, "point": None}])
        complex_str = builder.get_filter_complex()
        assert "trim=0.0:1.0" in complex_str
        assert "atrim=0.0:1.0" in complex_str
        # after cutting a single point, the builder re-concats down to one output
        assert builder.out_v.startswith("[cv") or builder.out_v.startswith("[scale_v")

    def test_filter_scale_with_dimensions(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        src = builder.out_v
        builder.filter_scale("1280", "-2")
        assert builder.filter_complex[-1] == f"{src}scale=1280:-2{builder.out_v}"

    def test_filter_scale_without_width_uses_copy(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        src = builder.out_v
        builder.filter_scale()
        assert builder.filter_complex[-1] == f"{src}copy{builder.out_v}"

    def test_get_filter_complex_joins_with_semicolons(self):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        assert builder.get_filter_complex() == ";".join(builder.filter_complex)


class TestValidateEncodeCudaUsage:
    def test_raises_when_nvenc_requested_without_cuda(self):
        with pytest.raises(ValueError, match="CUDA/NVENC is not available"):
            _validate_encode_cuda_usage(
                preset_args={"video": ["-c:v", "h264_nvenc"]},
                encode_cuda_available=False,
            )

    def test_allows_nvenc_when_cuda_available(self):
        _validate_encode_cuda_usage(
            preset_args={"video": ["-c:v", "h264_nvenc"]},
            encode_cuda_available=True,
        )

    def test_allows_cpu_codec_without_cuda(self):
        _validate_encode_cuda_usage(
            preset_args={"video": ["-c:v", "libx264"]},
            encode_cuda_available=False,
        )


class TestAddInputFiles:
    def test_without_cuda(self):
        inputs = [Path("/a.mp4"), Path("/b.mp4")]
        cmd = _add_input_files(inputs, decode_cuda_available=False)
        assert cmd == ["-i", "/a.mp4", "-i", "/b.mp4"]

    def test_with_cuda(self):
        inputs = [Path("/a.mp4")]
        cmd = _add_input_files(inputs, decode_cuda_available=True)
        assert cmd == ["-hwaccel", "cuda", "-i", "/a.mp4"]


class TestFfmpegCommandBuilder:
    def _builder(self, nb_inputs: int) -> FilterComplexBuilder:
        builder = FilterComplexBuilder(nb_inputs)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        return builder

    def test_output_file_required(self):
        with pytest.raises(ValueError, match="output_file must not be None"):
            ffmpeg_command_builder(
                filter_complex=self._builder(1),
                input_files=[Path("/a.mp4")],
                output_file=None,
                preset_args={"video": [], "audio": []},
            )

    def test_builds_expected_command(self, tmp_path: Path):
        inputs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"
        builder = self._builder(2)
        preset_args = {"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]}

        cmd = ffmpeg_command_builder(
            filter_complex=builder,
            input_files=inputs,
            output_file=output,
            preset_args=preset_args,
        )

        assert cmd[0] == "ffmpeg"
        assert cmd.count("-i") == 2
        assert "-filter_complex" in cmd
        assert "-c:v" in cmd
        assert "-c:a" in cmd
        assert "+faststart" in cmd
        assert str(output.absolute()) in cmd
        assert cmd[-1] == "-y"

    def test_includes_chapter_metadata(self, tmp_path: Path):
        inputs = [tmp_path / "a.mp4"]
        output = tmp_path / "out.mp4"
        metadata_path = tmp_path / "chapters.txt"
        metadata_path.write_text(";FFMETADATA1")
        builder = self._builder(1)

        cmd = ffmpeg_command_builder(
            filter_complex=builder,
            input_files=inputs,
            output_file=output,
            preset_args={"video": [], "audio": []},
            chapter_metadata_path=metadata_path,
        )

        assert str(metadata_path.absolute()) in cmd
        assert "-map_metadata" in cmd
        assert cmd[cmd.index("-map_metadata") + 1] == str(len(inputs))

    def test_rejects_nvenc_without_cuda(self, tmp_path: Path):
        with pytest.raises(ValueError):
            ffmpeg_command_builder(
                filter_complex=self._builder(1),
                input_files=[tmp_path / "a.mp4"],
                output_file=tmp_path / "out.mp4",
                preset_args={"video": ["-c:v", "h264_nvenc"], "audio": []},
                encode_cuda_available=False,
            )


class TestGetFps:
    def test_parses_frame_rate(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        stdout = json.dumps({"streams": [{"r_frame_rate": "30000/1001"}]})
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                args=a, returncode=0, stdout=stdout
            ),
        )
        fps = get_fps(tmp_path / "video.mp4")
        assert fps == pytest.approx(30000 / 1001)


class TestGetChapters:
    def test_parses_chapters(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        stdout = json.dumps(
            {"chapters": [{"start_time": "0.0", "end_time": "1.5"}]}
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                args=a, returncode=0, stdout=stdout
            ),
        )
        chapters = get_chapters(tmp_path / "video.mp4")
        assert chapters == [(0.0, 1.5)]

    def test_returns_empty_list_when_no_chapters(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                args=a, returncode=0, stdout=json.dumps({"chapters": []})
            ),
        )
        assert get_chapters(tmp_path / "video.mp4") == []


class TestWriteChaptersMetadata:
    def test_writes_expected_chapter_boundaries(self, tmp_path: Path):
        metadata_path = tmp_path / "chapters.txt"
        points = [
            {"in": 0, "out": 25, "point": None},
            {"in": 25, "out": 75, "point": None},
        ]

        write_chapters_metadata(points=points, metadata_path=metadata_path, fps=25)

        content = metadata_path.read_text()
        assert ";FFMETADATA1" in content
        assert "START=0" in content
        assert "END=1000" in content
        assert "START=1000" in content
        assert "END=3000" in content
        assert "title=point 0" in content
        assert "title=point 1" in content
