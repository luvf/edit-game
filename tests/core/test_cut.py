"""Tests for core.models.cut.Cut, focused on the pure OTIO parsing logic."""

from __future__ import annotations

import opentimelineio as otio
import pytest

from core.models.cut import Cut

FPS = 25


def _make_clip(start: float, duration: float) -> otio.schema.Clip:
    source_range = otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(start, FPS),
        duration=otio.opentime.RationalTime(duration, FPS),
    )
    # available_range must cover the source_range, and its start is used by
    # Cut.gen_from_otio as the "zero" reference point; keep it at 0 so
    # in/out timecodes in the test match the clip's own source_range values.
    media_range = otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(0, FPS),
        duration=otio.opentime.RationalTime(start + duration + 10, FPS),
    )
    return otio.schema.Clip(
        source_range=source_range,
        media_reference=otio.schema.MissingReference(available_range=media_range),
    )


def _otio_bytes(clips: list[tuple[float, float]]) -> bytes:
    timeline = otio.schema.Timeline()
    track = otio.schema.Track()
    for start, duration in clips:
        track.append(_make_clip(start, duration))
    timeline.tracks.append(track)
    return otio.adapters.otio_json.write_to_string(timeline).encode("utf-8")


class TestGenFromOtio:
    def test_separate_clips_become_separate_points(self):
        payload = Cut.gen_from_otio(_otio_bytes([(100, 50), (200, 30)]))

        assert payload["overlays"] == []
        assert payload["points"] == [
            {"in": 100, "out": 150},
            {"in": 200, "out": 230},
        ]

    def test_near_contiguous_clips_are_merged(self):
        # second clip starts 1 frame after the first one ends: merged.
        payload = Cut.gen_from_otio(_otio_bytes([(300, 20), (321, 10)]))

        assert payload["points"] == [{"in": 300, "out": 331}]

    def test_single_clip(self):
        payload = Cut.gen_from_otio(_otio_bytes([(0, 40)]))

        assert payload["points"] == [{"in": 0, "out": 40}]


class TestGenFromFile:
    def test_dispatches_to_otio_for_otio_type(self, game):
        cut = Cut(game=game, name="c", type_cut="OTIO")
        payload = cut.gen_from_file(_otio_bytes([(0, 10)]))
        assert payload == {"points": [{"in": 0, "out": 10}], "overlays": []}

    def test_returns_empty_for_other_types(self, game):
        cut = Cut(game=game, name="c", type_cut="MAN")
        assert cut.gen_from_file(b"irrelevant") == {}

    def test_accepts_str_content(self, game):
        cut = Cut(game=game, name="c", type_cut="OTIO")
        payload = cut.gen_from_file(_otio_bytes([(0, 10)]).decode("utf-8"))
        assert payload == {"points": [{"in": 0, "out": 10}], "overlays": []}


class TestJsonRoundtrip:
    def test_set_and_get_json(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")

        cut.set_json({"points": [{"in": 0, "out": 10}], "overlays": []})

        assert cut.get_json() == {"points": [{"in": 0, "out": 10}], "overlays": []}


class TestEnsureVideo:
    def test_creates_video_when_missing(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        assert cut.rendered_video is None

        cut.ensure_video()

        assert cut.rendered_video is not None
        cut.refresh_from_db()
        assert cut.rendered_video is not None

    def test_is_idempotent(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")
        cut.ensure_video()
        first = cut.rendered_video

        cut.ensure_video()

        assert cut.rendered_video_id == first.id


class TestEnqueueCutTimesGeneration:
    def test_creates_gen_cut_item(self, game, tmp_path):
        cut = Cut.objects.create(game=game, name="c", type_cut="VID")
        rendered_path = tmp_path / "rendered.mp4"

        item = cut.enqueue_cut_times_generation(rendered_path)

        assert item.cut == cut
        assert item.rendered_path == str(rendered_path)

    def test_custom_tmp_dir_is_stored(self, game, tmp_path):
        cut = Cut.objects.create(game=game, name="c", type_cut="VID")
        custom_tmp = tmp_path / "custom_tmp"

        item = cut.enqueue_cut_times_generation("x.mp4", tmp_dir=custom_tmp)

        assert item.tmp_dir == str(custom_tmp)


class TestEnqueueCutRender:
    def test_invalid_preset_raises(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")

        with pytest.raises(ValueError, match="Preset must be"):
            cut.enqueue_cut_render(preset="ultra")

    def test_creates_item_and_video(self, game):
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")

        item = cut.enqueue_cut_render(preset="low")

        assert item.cut == cut
        assert item.preset == "low"
        cut.refresh_from_db()
        assert cut.rendered_video is not None

    def test_run_now_executes_immediately(self, game, monkeypatch):
        from core.models.render_queue.ffmpeg import RenderQueueItemCut

        monkeypatch.setattr(RenderQueueItemCut, "_execute", lambda self: None)
        cut = Cut.objects.create(game=game, name="c", type_cut="MAN")

        item = cut.enqueue_cut_render(preset="low", run_now=True)

        # run() only calls _execute(); status bookkeeping is the worker's job.
        assert item.status == item.Status.CREATED
