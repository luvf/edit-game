"""Tests for jugger_video_manipulation.ffmpeg_utils."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jugger_video_manipulation.ffmpeg_utils import (
    CudaUse,
    ExtraInputs,
    FilterComplexBuilder,
    _add_input_files,
    _validate_encode_cuda_usage,
    ffmpeg_command_builder,
    get_chapters,
    get_fps,
    input_indices,
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
        # Video bounds sit half a frame back, between two frames; the audio
        # keeps its exact bounds.
        assert "trim=start=0.000000:end=0.980000" in complex_str
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


class TestCrossfadeBetweenPoints:
    """One point dissolving into the next, rather than cutting to it."""

    @staticmethod
    def _points():
        # Six, five and four seconds at 25 fps, in that order.
        return [
            {"in": 0, "out": 150, "point": None},
            {"in": 300, "out": 425, "point": None},
            {"in": 600, "out": 700, "point": None},
        ]

    @staticmethod
    def _cut(points, crossfade):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        builder.filter_cut(25, points, crossfade)
        return builder

    def test_without_a_crossfade_the_points_are_concatenated(self):
        builder = self._cut(self._points(), 0)

        graph = builder.get_filter_complex()
        assert "xfade" not in graph
        assert "concat=n=3" in graph

    def test_each_join_gets_its_transition(self):
        builder = self._cut(self._points(), 1.0)

        graph = builder.get_filter_complex()
        assert graph.count("xfade=transition=fade") == 2
        assert graph.count("acrossfade=d=1.000") == 2
        assert "concat" not in graph.split("copy[cv0]")[1]

    def test_the_offsets_are_counted_on_the_shortened_timeline(self):
        builder = self._cut(self._points(), 1.0)

        graph = builder.get_filter_complex()
        # First join five seconds in: six seconds of point, less the second
        # the transition takes. The second join four seconds after that:
        # 6 + 5 - 1 - 1 = 9.
        assert "duration=1.000:offset=5.000" in graph
        assert "duration=1.000:offset=9.000" in graph

    def test_a_short_point_shortens_its_transitions(self):
        # Half a second of point cannot give a second to each of its two
        # neighbours; xfade would refuse the graph outright.
        points = [
            {"in": 0, "out": 150, "point": None},
            {"in": 300, "out": 312, "point": None},
            {"in": 600, "out": 700, "point": None},
        ]

        graph = self._cut(points, 1.0).get_filter_complex()

        assert graph.count("duration=0.240") == 2

    def test_each_dissolve_is_pinned_to_4_2_0(self):
        graph = self._cut(self._points(), 1.0).get_filter_complex()

        assert graph.count(",format=pix_fmts=yuvj420p|yuv420p|yuv420p10le[xv") == 2

    def test_a_dissolved_render_stays_4_2_0_with_libx264(self, tmp_path):
        # Left to itself xfade negotiates 4:4:4 with libx264, a profile most
        # players refuse; this runs ffmpeg to check what actually comes out.
        clip = tmp_path / "rush.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=96x54:rate=25:duration=12",
                "-f", "lavfi", "-i", "sine=duration=12",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuvj420p", str(clip),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        builder = self._cut(self._points(), 1.0)
        out = tmp_path / "out.mp4"

        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(clip),
                "-filter_complex", builder.get_filter_complex(),
                "-map", builder.out_v, "-map", builder.out_a,
                "-c:v", "libx264", str(out),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip

        assert probe.stdout.strip() == "yuvj420p"

    def test_the_last_nodes_become_the_output(self):
        builder = self._cut(self._points(), 1.0)

        assert builder.out_v.startswith("[xv")
        assert builder.out_a.startswith("[xa")

    def test_a_point_that_keeps_nothing_is_dropped(self):
        # Otherwise the transitions and the scoreboard, which drops it, would
        # be one point out of step with each other.
        points = [
            {"in": 0, "out": 150, "point": None},
            {"in": 300, "out": 300, "point": None},
            {"in": 600, "out": 700, "point": None},
        ]

        graph = self._cut(points, 1.0).get_filter_complex()

        assert "split=2" in graph
        assert graph.count("xfade=transition=fade") == 1

    def test_a_single_point_has_nothing_to_dissolve_into(self):
        graph = self._cut([{"in": 0, "out": 150, "point": None}], 1.0)

        assert "xfade" not in graph.get_filter_complex()


class TestIntroCard:
    """The card in front of the match, and how it gets out of the way."""

    @staticmethod
    def _intro(fade):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        builder.filter_intro(
            card_index=2,
            silence_index=1,
            duration=4.0,
            fps=25,
            size=(1920, 1080),
            fade=fade,
        )
        return builder.get_filter_complex()

    def test_without_a_fade_the_card_is_concatenated(self):
        graph = self._intro(0.0)

        assert "concat=n=2" in graph
        assert "xfade" not in graph

    def test_the_card_dissolves_into_the_match(self):
        graph = self._intro(1.0)

        # Four seconds of card, the last of which is the dissolve.
        assert "duration=1.000:offset=3.000" in graph
        assert "acrossfade=d=1.000" in graph

    def test_both_branches_are_put_on_one_timebase(self):
        # A still given a frame rate and a rush from a container do not agree
        # on a timebase, and xfade refuses two inputs that disagree.
        graph = self._intro(1.0)

        assert graph.count("settb=AVTB") == 2


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

    def test_chapters_come_from_the_metadata_not_a_rush(self, tmp_path: Path):
        # A GoPro rush can carry a chapter of its own; ffmpeg would take it
        # over ours, being the first input that has any.
        inputs = [tmp_path / "GX011167.MP4", tmp_path / "GX021167.MP4"]
        metadata_path = tmp_path / "chapters.txt"
        metadata_path.write_text(";FFMETADATA1")

        cmd = ffmpeg_command_builder(
            filter_complex=self._builder(2),
            input_files=inputs,
            output_file=tmp_path / "out.mp4",
            preset_args={"video": [], "audio": []},
            chapter_metadata_path=metadata_path,
        )

        assert cmd[cmd.index("-map_chapters") + 1] == str(len(inputs))

    def test_no_chapter_mapping_without_metadata(self, tmp_path: Path):
        cmd = ffmpeg_command_builder(
            filter_complex=self._builder(1),
            input_files=[tmp_path / "a.mp4"],
            output_file=tmp_path / "out.mp4",
            preset_args={"video": [], "audio": []},
        )

        assert "-map_chapters" not in cmd

    def test_rejects_nvenc_without_cuda(self, tmp_path: Path):
        with pytest.raises(ValueError):
            ffmpeg_command_builder(
                filter_complex=self._builder(1),
                input_files=[tmp_path / "a.mp4"],
                output_file=tmp_path / "out.mp4",
                preset_args={"video": ["-c:v", "h264_nvenc"], "audio": []},
                cuda=CudaUse(encode=False),
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
        stdout = json.dumps({"chapters": [{"start_time": "0.0", "end_time": "1.5"}]})
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

    def test_the_chapters_follow_the_transitions(self, tmp_path: Path):
        # Two points of two seconds joined by a half-second dissolve: the
        # second chapter starts where its point starts, which is half a
        # second before the first one ends.
        metadata_path = tmp_path / "chapters.txt"
        points = [
            {"in": 0, "out": 50, "point": None},
            {"in": 100, "out": 150, "point": None},
        ]

        write_chapters_metadata(
            points=points, metadata_path=metadata_path, fps=25, crossfade=0.5
        )

        content = metadata_path.read_text()
        assert "START=0\nEND=2000" in content
        assert "START=1500\nEND=3500" in content

    def test_an_opening_card_pushes_the_chapters_back(self, tmp_path: Path):
        metadata_path = tmp_path / "chapters.txt"
        points = [{"in": 0, "out": 50, "point": None}]

        write_chapters_metadata(
            points=points, metadata_path=metadata_path, fps=25, offset=3.0
        )

        assert "START=3000\nEND=5000" in metadata_path.read_text()

    def test_a_point_that_keeps_nothing_gets_no_chapter(self, tmp_path: Path):
        metadata_path = tmp_path / "chapters.txt"
        points = [
            {"in": 0, "out": 50, "point": None},
            {"in": 100, "out": 100, "point": None},
        ]

        write_chapters_metadata(points=points, metadata_path=metadata_path, fps=25)

        assert "title=point 1" not in metadata_path.read_text()


class TestFilterOverlay:
    """Still overlays, each painted only over its own window."""

    @pytest.fixture()
    def builder(self):
        b = FilterComplexBuilder(1)
        b.out_v, b.out_a = "[cv0]", "[ca0]"
        return b

    def test_no_overlays_changes_nothing(self, builder):
        before = builder.out_v

        builder.filter_overlay([])

        assert builder.out_v == before
        assert builder.filter_complex == []

    def test_one_overlay_is_bounded_by_its_window(self, builder):
        builder.filter_overlay([(3, 1.5, 4.25)])

        assert "enable='gte(t,1.500)*lt(t,4.250)'" in builder.filter_complex[0]
        assert "[3:v]" in builder.filter_complex[0]

    def test_overlays_chain_onto_one_another(self, builder):
        builder.filter_overlay([(3, 0.0, 1.0), (4, 1.0, 2.0)])

        first, second = builder.filter_complex
        # The second reads the node the first wrote.
        node = first.rsplit("[", 1)[1].rstrip("]")
        assert f"[{node}]" in second

    def test_the_last_node_becomes_the_output(self, builder):
        builder.filter_overlay([(3, 0.0, 1.0), (4, 1.0, 2.0)])

        # Whatever the last filter wrote is what the rest of the graph reads.
        assert builder.filter_complex[-1].endswith(builder.out_v)

    def test_the_audio_output_is_untouched(self, builder):
        builder.filter_overlay([(3, 0.0, 1.0)])

        assert builder.out_a == "[ca0]"


class TestOverlayInputs:
    """Overlay images are inputs too, and must not shift the metadata index."""

    def test_overlay_files_are_added_as_inputs(self):
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            extras=ExtraInputs(overlays=[Path("/ov0.png"), Path("/ov1.png")]),
        )

        assert "/ov0.png" in cmd
        assert "/ov1.png" in cmd

    def test_they_come_after_the_metadata_input(self, tmp_path):
        metadata = tmp_path / "meta.txt"
        metadata.write_text("")
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            chapter_metadata_path=metadata,
            extras=ExtraInputs(overlays=[Path("/ov0.png")]),
        )

        assert cmd.index(str(metadata.absolute())) < cmd.index("/ov0.png")

    def test_map_metadata_still_points_at_the_metadata(self, tmp_path):
        metadata = tmp_path / "meta.txt"
        metadata.write_text("")
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            chapter_metadata_path=metadata,
            extras=ExtraInputs(overlays=[Path("/ov0.png"), Path("/ov1.png")]),
        )

        # One video input, so the metadata is input 1 whatever follows it.
        assert cmd[cmd.index("-map_metadata") + 1] == "1"


def _builder_with_outputs() -> FilterComplexBuilder:
    builder = FilterComplexBuilder(1)
    builder.out_v, builder.out_a = "[cv0]", "[ca0]"
    return builder


class TestInputIndices:
    """One place knows the input order; getting it wrong aims a filter wrong."""

    def test_plain_render(self):
        indices = input_indices(3, has_metadata=False, has_silence=False)

        assert indices.silence is None
        assert indices.first_overlay == 3

    def test_metadata_shifts_the_overlays(self):
        indices = input_indices(3, has_metadata=True, has_silence=False)

        assert indices.first_overlay == 4

    def test_silence_comes_after_the_metadata(self):
        indices = input_indices(3, has_metadata=True, has_silence=True)

        assert indices.silence == 4
        assert indices.first_overlay == 5

    def test_silence_without_metadata(self):
        indices = input_indices(3, has_metadata=False, has_silence=True)

        assert indices.silence == 3
        assert indices.first_overlay == 4

    def test_no_silence_leaves_no_gap(self):
        # The bug this guards: offsetting for a silent input that was never
        # added pointed every overlay one index too far.
        indices = input_indices(7, has_metadata=False, has_silence=False)

        assert indices.first_overlay == 7


class TestSilenceInput:
    def test_it_is_added_when_asked_for(self):
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            extras=ExtraInputs(silence_seconds=4.0),
        )

        assert any("anullsrc" in argument for argument in cmd)

    def test_it_sits_between_the_metadata_and_the_images(self, tmp_path):
        metadata = tmp_path / "meta.txt"
        metadata.write_text("")
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            chapter_metadata_path=metadata,
            extras=ExtraInputs(overlays=[Path("/ov0.png")], silence_seconds=4.0),
        )

        silence = next(i for i, a in enumerate(cmd) if "anullsrc" in a)
        assert cmd.index(str(metadata.absolute())) < silence < cmd.index("/ov0.png")

    def test_map_metadata_is_unaffected(self, tmp_path):
        metadata = tmp_path / "meta.txt"
        metadata.write_text("")
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
            chapter_metadata_path=metadata,
            extras=ExtraInputs(overlays=[Path("/ov0.png")], silence_seconds=4.0),
        )

        assert cmd[cmd.index("-map_metadata") + 1] == "1"

    def test_none_adds_nothing(self):
        cmd = ffmpeg_command_builder(
            filter_complex=_builder_with_outputs(),
            input_files=[Path("/a.mp4")],
            output_file=Path("/out.mp4"),
            preset_args={"video": ["-c:v", "libx264"], "audio": ["-c:a", "aac"]},
        )

        assert not any("anullsrc" in argument for argument in cmd)


class TestMovingIntroGraph:
    """The footage before the first point, blurred behind the card."""

    @staticmethod
    def _graph(fade=1.0):
        builder = FilterComplexBuilder(1)
        builder.filter_concat(builder.inputs_v, builder.inputs_a)
        spare = builder.filter_branch()
        builder.filter_cut(25, [{"in": 250, "out": 500, "point": None}])
        builder.filter_intro_video(
            spare,
            card_index=3,
            start_frame=175,
            duration=4.0,
            fade=fade,
            fps=25,
            size=(1280, 720),
        )
        return builder, builder.get_filter_complex()

    def test_the_rushes_are_split_before_the_points_are_cut(self):
        _, graph = self._graph()
        chains = graph.split(";")
        split = next(i for i, chain in enumerate(chains) if "split=2[main_v" in chain)
        trim = next(
            i for i, chain in enumerate(chains) if "trim=start=9.980000" in chain
        )

        assert split < trim

    def test_the_footage_is_taken_from_before_the_point(self):
        _, graph = self._graph()

        # 175 frames at 25 fps, half a frame back; 100 frames of footage.
        assert "trim=start=6.980000:end=10.980000" in graph

    def test_it_is_blurred_and_shaded(self):
        _, graph = self._graph()

        # 16 at 1080 lines is 10.67 at 720.
        assert "gblur=sigma=10.67" in graph
        # Dimmed on brightness only: a dark veil greyed the colours out.
        assert "lutyuv=y=val*0.62" in graph
        assert "drawbox" not in graph

    def test_the_card_is_laid_over_it(self):
        _, graph = self._graph()

        assert "[3:v]overlay=0:0" in graph

    def test_its_sound_is_brought_down(self):
        _, graph = self._graph()

        assert "atrim=start=7.000000:end=11.000000" in graph
        assert "volume=0.25" in graph

    def test_it_dissolves_into_the_first_point_as_it_begins(self):
        _, graph = self._graph()

        assert "duration=1.000:offset=3.000" in graph
        assert "acrossfade=d=1.000" in graph

    def test_no_silence_is_needed(self):
        _, graph = self._graph()

        assert ":a]atrim=duration" not in graph

    def test_without_a_fade_it_is_concatenated(self):
        _, graph = self._graph(fade=0.0)

        assert "xfade" not in graph.split("[intro_v")[-1]
        assert "concat=n=2" in graph
