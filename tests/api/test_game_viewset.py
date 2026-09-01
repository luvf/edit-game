"""Tests for the /api/games/ endpoints."""

from __future__ import annotations

from django.urls import reverse
from model_bakery import baker

from core.models.cut import Cut
from core.models.render_queue.base import RenderQueueItemBase
from core.models.render_queue.ffmpeg import RenderQueueItemArchive


class TestListAndRetrieve:
    def test_list_returns_games(self, api_client, game):
        response = api_client.get(reverse("game-list"))
        assert response.status_code == 200
        # GameViewSet has no pagination_class and REST_FRAMEWORK doesn't set
        # a default one, so list responses are plain (unpaginated) arrays.
        assert len(response.data) == 1

    def test_retrieve_includes_hal_links(self, api_client, game):
        response = api_client.get(reverse("game-detail", args=[game.pk]))
        assert response.status_code == 200
        assert "_links" in response.data
        assert "self" in response.data["_links"]

    def test_embed_query_param_limits_embedded_objects(self, api_client, game):
        response = api_client.get(
            reverse("game-detail", args=[game.pk]), {"embed": "tournament"}
        )
        assert response.status_code == 200
        assert "tournament" in response.data.get("_embedded", {})
        assert "team1" not in response.data.get("_embedded", {})

    def test_no_embed_query_param_removes_embedded_section(self, api_client, game):
        response = api_client.get(
            reverse("game-detail", args=[game.pk]), {"no_embed": "true"}
        )
        assert response.status_code == 200
        assert "_embedded" not in response.data

    def test_fields_query_param_filters_response(self, api_client, game):
        response = api_client.get(
            reverse("game-detail", args=[game.pk]), {"fields": "name"}
        )
        assert response.status_code == 200
        assert set(response.data.keys()) <= {"name", "_links", "_embedded"}
        assert response.data["name"] == game.name

    def test_archive_video_relation_is_absent_without_archive(self, api_client, game):
        response = api_client.get(reverse("game-detail", args=[game.pk]))
        assert response.status_code == 200
        assert "archive_video" not in response.data["_links"]
        assert "archive_video" not in response.data.get("_embedded", {})

    def test_archive_video_relation_is_exposed_when_set(self, api_client, game):
        game.archive_video = baker.make("core.Video", name="archive")
        game.save(update_fields=["archive_video"])

        response = api_client.get(reverse("game-detail", args=[game.pk]))

        assert response.status_code == 200
        assert response.data["_links"]["archive_video"]["href"].endswith(
            f"/videos/{game.archive_video.pk}/"
        )
        assert response.data["_embedded"]["archive_video"]["pk"] == (
            game.archive_video.pk
        )


class TestCuts:
    def test_returns_cuts_for_game(self, api_client, game):
        Cut.objects.create(game=game, name="c1", type_cut="MAN")
        response = api_client.get(reverse("game-cuts", args=[game.pk]))
        assert response.status_code == 200
        assert len(response.data) == 1


class TestGenerateProxy:
    def test_enqueues_a_proxy_render_item(self, api_client, game):
        response = api_client.post(
            reverse("game-generate-proxy", args=[game.pk]), {"quality": "low"}
        )
        assert response.status_code == 200
        assert response.data["job_type"] == RenderQueueItemBase.JobType.GAME_PROXY

    def test_invalid_preset_returns_400(self, api_client, game):
        response = api_client.post(
            reverse("game-generate-proxy", args=[game.pk]), {"quality": "invalid"}
        )
        assert response.status_code == 400


class TestCreateCut:
    def test_creates_a_manual_cut_by_default(self, api_client, game):
        response = api_client.post(
            reverse("game-create-cut", args=[game.pk]), {"name": "My cut"}
        )
        assert response.status_code == 200
        assert response.data["name"] == "My cut"
        assert response.data["type_cut"] == "MAN"
        assert Cut.objects.filter(game=game, name="My cut").exists()


class TestCreateArchive:
    def test_defaults_to_the_archive_preset(self, api_client, game):
        """No preset must mean the archive default, not a cut preset.

        The preset also names the VideoFile quality the result is filed
        under, so a wrong default writes the archive where nothing looks
        for it.
        """
        response = api_client.post(reverse("game-create-archive", args=[game.pk]))

        assert response.status_code == 201
        assert response.data["preset"] == RenderQueueItemArchive.DEFAULT_PRESET

    def test_creates_archive_render_item(self, api_client, game):
        response = api_client.post(
            reverse("game-create-archive", args=[game.pk]), {"preset": "high"}
        )
        assert response.status_code == 201
        assert response.data["status"] == RenderQueueItemBase.Status.CREATED

    def test_conflicts_when_pending_item_already_exists(self, api_client, game):
        baker.make(
            "core.RenderQueueItemArchive",
            game=game,
            preset="high",
            status=RenderQueueItemBase.Status.WAITING,
        )

        response = api_client.post(
            reverse("game-create-archive", args=[game.pk]), {"preset": "high"}
        )

        assert response.status_code == 409
        assert "archive_video_id" in response.data

    def test_force_bypasses_conflict(self, api_client, game):
        baker.make(
            "core.RenderQueueItemArchive",
            game=game,
            preset="high",
            status=RenderQueueItemBase.Status.WAITING,
        )

        response = api_client.post(
            reverse("game-create-archive", args=[game.pk]),
            {"preset": "high", "force": True},
        )

        assert response.status_code == 201
        assert (
            RenderQueueItemArchive.objects.filter(game=game, preset="high").count() == 2
        )
