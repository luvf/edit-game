"""Tests for core.youtube_interaction.yt_interaction.YtVideoMetadata (pure logic only).

YTInteraction itself requires real Google OAuth credentials and network access
and is out of scope for this pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.youtube_interaction.yt_interaction import YtVideoMetadata


class TestToJson:
    def test_public_video_has_empty_status(self):
        meta = YtVideoMetadata(
            "id1", "title", "desc", datetime(2020, 1, 1, tzinfo=UTC), "public"
        )
        body = meta.to_json()
        assert body["id"] == "id1"
        assert body["snippet"]["title"] == "title"
        assert body["snippet"]["description"] == "desc"
        assert body["status"] == {}


class TestSetStatus:
    def test_future_private_date_schedules_publish(self):
        future = datetime.now(UTC) + timedelta(days=1)
        meta = YtVideoMetadata("id1", "t", "d", future, "private")

        assert meta._set_status() == {
            "privacyStatus": "private",
            "publishAt": future.isoformat(),
        }

    def test_past_private_date_returns_empty(self):
        past = datetime.now(UTC) - timedelta(days=1)
        meta = YtVideoMetadata("id1", "t", "d", past, "private")

        assert meta._set_status() == {}

    def test_future_unlisted_date_also_schedules_publish(self):
        future = datetime.now(UTC) + timedelta(days=1)
        meta = YtVideoMetadata("id1", "t", "d", future, "unlisted")

        assert meta._set_status()["privacyStatus"] == "private"

    def test_public_status_ignores_date(self):
        future = datetime.now(UTC) + timedelta(days=1)
        meta = YtVideoMetadata("id1", "t", "d", future, "public")

        assert meta._set_status() == {}


class TestFromJson:
    def test_video_kind_uses_id_and_publish_at(self):
        data = {
            "kind": "youtube#video",
            "id": "vid123",
            "snippet": {"title": "T", "description": "D"},
            "status": {
                "privacyStatus": "private",
                "publishAt": "2024-01-01T10:00:00+00:00",
            },
        }
        meta = YtVideoMetadata.from_json(data)

        assert meta.video_id == "vid123"
        assert meta.title == "T"
        assert meta.description == "D"
        assert meta.status == "private"
        assert meta.date == datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

    def test_playlist_item_uses_resource_id_and_published_at(self):
        data = {
            "kind": "youtube#playlistItem",
            "snippet": {
                "title": "T2",
                "description": "D2",
                "publishedAt": "2023-05-05T08:00:00+00:00",
                "resourceId": {"videoId": "vidABC"},
            },
            "status": {"privacyStatus": "public"},
        }
        meta = YtVideoMetadata.from_json(data)

        assert meta.video_id == "vidABC"
        assert meta.status == "public"
        assert meta.date == datetime(2023, 5, 5, 8, 0, 0, tzinfo=UTC)
