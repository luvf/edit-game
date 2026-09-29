"""Creating a team from the editor's bubble, through the real API."""

from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.models.tournament import Team


def _png() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (200, 40, 40, 255)).save(buffer, format="PNG")
    return SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")


class TestCreateTeam:
    def test_a_team_can_be_created_without_a_logo(self, api_client, db):
        response = api_client.post(
            "/api/teams/",
            {"name": "Les Nouveaux", "short_name": "LN"},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        team = Team.objects.get(name="Les Nouveaux")
        assert team.short_name == "LN"
        # The model's default stands in for the logo: the render generates one.
        assert team.image.name == "default.png"

    def test_the_created_team_links_to_itself(self, api_client, db):
        # The editor selects the new team by this link, as it does any other.
        response = api_client.post(
            "/api/teams/",
            {"name": "Les Nouveaux", "short_name": "LN"},
            format="multipart",
        )

        assert response.json()["_links"]["self"]["href"].endswith(
            f"/api/teams/{Team.objects.get(name='Les Nouveaux').pk}/"
        )

    def test_a_logo_can_come_with_it(self, api_client, db):
        response = api_client.post(
            "/api/teams/",
            {"name": "Avec Logo", "short_name": "AL", "image": _png()},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        assert Team.objects.get(name="Avec Logo").image.name != "default.png"

    def test_a_short_name_too_long_is_refused_with_a_reason(self, api_client, db):
        response = api_client.post(
            "/api/teams/",
            {"name": "Trop Long", "short_name": "ABCDEFGHIJK"},
            format="multipart",
        )

        assert response.status_code == 400
        assert "short_name" in response.json()
