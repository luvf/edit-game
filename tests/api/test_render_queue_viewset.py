"""Tests for the /api/render-queue/ endpoints."""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from model_bakery import baker

from core.models.cut import Cut
from core.models.render_queue.base import RenderQueueItemBase

Status = RenderQueueItemBase.Status


class TestRun:
    def test_run_transitions_to_waiting_and_triggers_worker(self, api_client, game):
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.CREATED)

        with patch("api.views.run_async_task") as mock_run_async:
            response = api_client.post(reverse("renderqueue-run", args=[item.pk]))

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.status == Status.WAITING
        mock_run_async.assert_called_once_with("core.tasks.process_render_queue")

    def test_run_returns_409_when_already_running(self, api_client, game):
        item = baker.make("core.RenderQueueItemProxy", game=game, status=Status.RUNNING)

        with patch("api.views.run_async_task"):
            response = api_client.post(reverse("renderqueue-run", args=[item.pk]))

        assert response.status_code == 409


class TestReset:
    def test_reset_returns_item_to_created(self, api_client, game):
        item = baker.make(
            "core.RenderQueueItemProxy",
            game=game,
            status=Status.FAILED,
            error="boom",
            pid=None,
        )

        response = api_client.post(reverse("renderqueue-reset", args=[item.pk]))

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.status == Status.CREATED
        assert item.error == ""


class TestSerializerPolymorphicDispatch:
    def test_cut_item_exposes_cut_id_and_metadata(self, api_client, game):
        cut = Cut.objects.create(game=game, name="c1", type_cut="MAN")
        item = baker.make("core.RenderQueueItemCut", cut=cut, preset="low")

        response = api_client.get(reverse("renderqueue-detail", args=[item.pk]))

        assert response.status_code == 200
        assert response.data["cut"] == cut.pk
        # .game resolves via cut.game for cut-type items, not just proxy/archive.
        assert response.data["game"] == game.pk
        assert response.data["metadata"] == "low"

    def test_proxy_item_exposes_game_id(self, api_client, game):
        item = baker.make("core.RenderQueueItemProxy", game=game, preset="medium")

        response = api_client.get(reverse("renderqueue-detail", args=[item.pk]))

        assert response.status_code == 200
        assert response.data["game"] == game.pk
        assert response.data["cut"] is None
        assert response.data["metadata"] == "medium"
