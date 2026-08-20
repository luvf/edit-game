"""Tests for the /api/tournaments/ endpoints."""

from __future__ import annotations

from django.urls import reverse
from django.utils.text import slugify

from core.models.tournament import Tournament


class TestCreate:
    def test_creates_tournament(self, api_client, db, tmp_path):
        payload = {
            "name": "My Tournament",
            "short_name": "MT",
            "date": "2024-01-01",
            "tournament_dir": "my-tournament",
            "drive_dir": str(tmp_path),
        }

        response = api_client.post(reverse("tournament-list"), payload)

        assert response.status_code == 201
        tournament = Tournament.objects.get(name="My Tournament")
        assert tournament.slug == slugify("My Tournament")
        assert tournament.tournament_dir == "my-tournament"

    def test_missing_required_field_returns_400(self, api_client, db):
        response = api_client.post(
            reverse("tournament-list"), {"name": "Incomplete"}
        )
        assert response.status_code == 400


class TestArchive:
    def test_archive_updates_drive_dir(self, api_client, tournament, settings):
        response = api_client.post(reverse("tournament-archive", args=[tournament.pk]))

        assert response.status_code == 200
        tournament.refresh_from_db()
        assert tournament.drive_dir == str(settings.TOURNAMENTS_ARCHIVE_DIR)

    def test_archived_tournament_hides_archive_link_and_flags_is_archived(
        self, api_client, tournament, settings
    ):
        tournament.drive_dir = str(settings.TOURNAMENTS_ARCHIVE_DIR)
        tournament.save(update_fields=["drive_dir"])

        response = api_client.get(reverse("tournament-detail", args=[tournament.pk]))

        assert response.status_code == 200
        assert response.data["is_archived"] is True
        assert "archive" not in response.data.get("_links", {})

    def test_non_archived_tournament_shows_archive_link(self, api_client, tournament):
        response = api_client.get(reverse("tournament-detail", args=[tournament.pk]))

        assert response.data["is_archived"] is False
        assert "archive" in response.data["_links"]


class TestGames:
    def test_returns_games_for_tournament(self, api_client, game):
        response = api_client.get(reverse("tournament-games", args=[game.tournament.pk]))

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["name"] == game.name
