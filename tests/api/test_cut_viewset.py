"""Tests for the /api/cuts/ endpoints."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from django.core.files.base import ContentFile
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


class TestCurves:
    def _cut_with_curves(self, game, steps: int = 600):
        """An ML cut carrying curves, as the queue leaves it."""
        cut = Cut.objects.create(game=game, name="ml", type_cut="ML")
        cut.set_json(
            {
                "points": [],
                "overlays": [],
                "comment": {
                    "fps": 59.94,
                    "decode": {"threshold": {"in": 0.5, "out": 0.7}},
                    "model": {"run": "ast_ms_268"},
                },
            }
        )
        buffer = io.BytesIO()
        peak = np.zeros(steps, dtype=np.float32)
        peak[3] = 0.9
        np.savez_compressed(
            buffer,
            **{
                "in": peak,
                "out": np.zeros(steps, dtype=np.float32),
                "inside": np.full(steps, 0.4, dtype=np.float32),
                "times": ((np.arange(steps) + 0.5) * 0.1).astype(np.float32),
            },
        )
        cut.curves_file.save("curves.npz", ContentFile(buffer.getvalue()), save=True)
        return cut

    def test_serves_the_curves_with_what_is_needed_to_place_them(
        self, api_client, game
    ):
        cut = self._cut_with_curves(game)

        response = api_client.get(reverse("cut-curves", args=[cut.pk]))

        assert response.status_code == 200
        assert response.data["points"] == 600
        assert response.data["steps"] == 600
        assert response.data["hop"] == pytest.approx(0.1, abs=1e-3)
        # The frame rate and the thresholds ride along: without them the front
        # cannot put the curve on the timeline's axis, nor draw the line a
        # peak had to clear.
        assert response.data["fps"] == pytest.approx(59.94)
        assert response.data["decode"]["threshold"]["in"] == 0.5
        assert response.data["run"] == "ast_ms_268"

    def test_the_resolution_is_the_callers_to_choose(self, api_client, game):
        cut = self._cut_with_curves(game)

        response = api_client.get(reverse("cut-curves", args=[cut.pk]), {"points": 100})

        assert len(response.data["in"]) == 100
        assert response.data["steps"] == 600

    def test_a_cut_without_curves_says_so(self, api_client, game):
        cut = Cut.objects.create(game=game, name="manual", type_cut="MAN")

        response = api_client.get(reverse("cut-curves", args=[cut.pk]))

        assert response.status_code == 404

    def test_a_curves_file_gone_from_disk_is_not_a_crash(self, api_client, game):
        cut = self._cut_with_curves(game)
        Path(cut.curves_file.path).unlink()

        response = api_client.get(reverse("cut-curves", args=[cut.pk]))

        assert response.status_code == 404


class TestRedecode:
    """Turning a threshold again, months later, without a GPU."""

    def _cut_with_a_decodable_point(self, game, **comment):
        """A cut whose curves hold one clean point, from 10 s to 40 s."""
        steps = 600
        channels = {
            "in": np.zeros(steps, dtype=np.float32),
            "out": np.zeros(steps, dtype=np.float32),
            "inside": np.full(steps, 0.05, dtype=np.float32),
            "times": ((np.arange(steps) + 0.5) * 0.1).astype(np.float32),
        }
        channels["in"][100] = 0.9
        channels["out"][400] = 0.9
        channels["inside"][100:400] = 0.9

        cut = Cut.objects.create(game=game, name="ml", type_cut="ML")
        cut.set_json(
            {
                "points": [{"in": 0, "out": 1}],
                "overlays": [],
                "comment": {"fps": 60.0, "model": {"run": "ast_ms_268"}, **comment},
            }
        )
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **channels)
        cut.curves_file.save("curves.npz", ContentFile(buffer.getvalue()), save=True)
        return cut

    def test_a_preview_changes_nothing_on_disk(self, api_client, game):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(reverse("cut-redecode", args=[cut.pk]))

        assert response.status_code == 200
        assert response.data["applied"] is False
        assert response.data["segments"] == 1
        # 10 s at 60 fps. The stored times are step centres, so the peak of
        # step 100 sits at 10.05 s: half a step, not a rounding accident.
        assert response.data["points"][0]["in"] == pytest.approx(603, abs=2)
        cut.refresh_from_db()
        assert cut.get_json()["points"] == [{"in": 0, "out": 1}]

    def test_applying_rewrites_the_cut(self, api_client, game):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(
            reverse("cut-redecode", args=[cut.pk]), {"apply": True}
        )

        assert response.data["applied"] is True
        cut.refresh_from_db()
        points = cut.get_json()["points"]
        assert len(points) == 1
        assert points[0]["in"] == pytest.approx(603, abs=2)
        assert cut.get_json()["comment"]["model"]["redecoded"] is True

    def test_a_threshold_above_the_peak_drops_the_point(self, api_client, game):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(
            reverse("cut-redecode", args=[cut.pk]), {"threshold_in": 0.99}
        )

        assert response.data["segments"] == 0

    def test_out_of_range_values_are_clamped_rather_than_refused(
        self, api_client, game
    ):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(
            reverse("cut-redecode", args=[cut.pk]),
            {"threshold_in": 42, "threshold_out": -3},
        )

        # Clamped to [0, 1]: `in` becomes unreachable, so nothing is proposed.
        assert response.status_code == 200
        assert response.data["segments"] == 0

    def test_nonsense_values_fall_back_to_the_defaults(self, api_client, game):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(
            reverse("cut-redecode", args=[cut.pk]), {"threshold_in": "beaucoup"}
        )

        assert response.status_code == 200
        assert response.data["segments"] == 1

    def test_without_the_envelope_the_boundaries_are_not_snapped(
        self, api_client, game
    ):
        cut = self._cut_with_a_decodable_point(game)

        response = api_client.post(reverse("cut-redecode", args=[cut.pk]))

        # The cache is empty in tests: the answer says so rather than pretending.
        assert response.data["snapped"] is False

    def test_with_the_envelope_the_boundaries_are_snapped(
        self, api_client, game, settings
    ):
        from game_autoedit.data.beats import save_envelope

        cut = self._cut_with_a_decodable_point(game)
        beats = Path(settings.AUTOEDIT_CACHE) / "beats"
        beats.mkdir(parents=True, exist_ok=True)
        # A drum every 1.5 s, which is what the snapper looks for.
        envelope = np.zeros(6000, dtype=np.float32)
        envelope[::150] = 1.0
        save_envelope(beats, game.pk, envelope)

        response = api_client.post(reverse("cut-redecode", args=[cut.pk]))

        assert response.data["snapped"] is True

    def test_a_cut_without_curves_says_so(self, api_client, game):
        cut = Cut.objects.create(game=game, name="manual", type_cut="MAN")

        response = api_client.post(reverse("cut-redecode", args=[cut.pk]))

        assert response.status_code == 404
