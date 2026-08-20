"""Tests for the /api/videos/ endpoints (read-only)."""

from __future__ import annotations

from django.urls import reverse
from model_bakery import baker

from core.models.video import VideoFile


class TestList:
    def test_list_is_paginated(self, api_client, game):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])

        response = api_client.get(reverse("video-list"))

        assert response.status_code == 200
        assert response.data["count"] == 1
        assert len(response.data["results"]) == 1


class TestRetrieve:
    def test_owner_type_is_game_for_proxy_video(self, api_client, game):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])

        response = api_client.get(reverse("video-detail", args=[video.pk]))

        assert response.status_code == 200
        assert response.data["owner_type"] == "game"

    def test_files_and_qualities_reflect_video_files(self, api_client, game, tmp_path):
        video = baker.make("core.Video")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])

        real_file = tmp_path / "out.mp4"
        real_file.write_bytes(b"x")
        baker.make(
            "core.VideoFile",
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
            path=str(real_file),
        )

        response = api_client.get(reverse("video-detail", args=[video.pk]))

        assert response.status_code == 200
        assert response.data["qualities"] == ["low"]
        assert "low" in response.data["files"]
