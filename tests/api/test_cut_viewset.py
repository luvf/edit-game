"""Tests for the /api/cuts/ endpoints."""

from __future__ import annotations

import io
import json

from django.urls import reverse

from core.models.cut import Cut
from core.models.render_queue.ffmpeg import RenderQueueItemCut


class TestRetrieveAndUpdate:
    def test_retrieve_cut(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")
        response = api_client.get(reverse("cut-detail", args=[cut.pk]))
        assert response.status_code == 200
        assert response.data["name"] == "c1"

    def test_update_with_valid_json_string(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")
        payload = json.dumps({"points": [{"in": 0, "out": 10}], "overlays": []})

        response = api_client.patch(
            reverse("cut-detail", args=[cut.pk]), {"json_file": payload}, format="json"
        )

        assert response.status_code == 200
        cut.refresh_from_db()
        assert cut.get_json() == {"points": [{"in": 0, "out": 10}], "overlays": []}

    def test_update_with_dict_payload(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")

        response = api_client.patch(
            reverse("cut-detail", args=[cut.pk]),
            {"json_file": {"points": [], "overlays": []}},
            format="json",
        )

        assert response.status_code == 200
        cut.refresh_from_db()
        assert cut.get_json() == {"points": [], "overlays": []}

    def test_update_with_invalid_json_string_returns_400(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")

        response = api_client.patch(
            reverse("cut-detail", args=[cut.pk]),
            {"json_file": "not valid json"},
            format="json",
        )

        assert response.status_code == 400


class TestRender:
    def test_to_queue_creates_item_without_running_it(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")

        response = api_client.post(
            reverse("cut-render", args=[cut.pk]),
            {"preset": "low", "to_queue": "true"},
        )

        assert response.status_code == 200
        item = RenderQueueItemCut.objects.get(cut=cut)
        assert item.preset == "low"

    def test_invalid_preset_when_queued_returns_500(self, api_client, game):
        # enqueue_cut_render raises ValueError for a bad preset; the view
        # turns any exception (not just ValueError) into a 500 response.
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")

        response = api_client.post(
            reverse("cut-render", args=[cut.pk]),
            {"preset": "not-a-preset", "to_queue": "true"},
        )

        assert response.status_code == 500


class TestGenFromFile:
    def test_uploads_otio_file_and_writes_points(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="OTIO")
        import opentimelineio as otio

        timeline = otio.schema.Timeline()
        track = otio.schema.Track()
        track.append(
            otio.schema.Clip(
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, 25),
                    duration=otio.opentime.RationalTime(50, 25),
                ),
                media_reference=otio.schema.MissingReference(
                    available_range=otio.opentime.TimeRange(
                        start_time=otio.opentime.RationalTime(0, 25),
                        duration=otio.opentime.RationalTime(1000, 25),
                    )
                ),
            )
        )
        timeline.tracks.append(track)
        content = otio.adapters.otio_json.write_to_string(timeline).encode("utf-8")
        upload = io.BytesIO(content)
        upload.name = "timeline.otio"

        response = api_client.post(
            reverse("cut-gen-from-file", args=[cut.pk]), {"upload_file": upload}
        )

        assert response.status_code == 200
        cut.refresh_from_db()
        assert cut.get_json() == {"points": [{"in": 0, "out": 50}], "overlays": []}

    def test_missing_file_returns_400(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")
        response = api_client.post(reverse("cut-gen-from-file", args=[cut.pk]), {})
        assert response.status_code == 400

    def test_unsupported_extension_returns_400(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")
        upload = io.BytesIO(b"not relevant")
        upload.name = "file.txt"

        response = api_client.post(
            reverse("cut-gen-from-file", args=[cut.pk]), {"upload_file": upload}
        )

        assert response.status_code == 400


class TestCutTypes:
    def test_returns_available_cut_types(self, api_client, db):
        response = api_client.get(reverse("cut-cut-types"))
        assert response.status_code == 200
        codes = {entry["code"] for entry in response.data}
        assert codes == {code for code, _ in Cut.CUT_TYPES}
