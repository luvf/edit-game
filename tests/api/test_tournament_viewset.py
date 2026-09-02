"""Tests for the /api/tournaments/ endpoints."""

from __future__ import annotations

from django.urls import reverse
from django.utils.text import slugify
from model_bakery import baker

from core.models.render_queue.ffmpeg import RenderQueueItemArchive
from core.models.tournament import Tournament
from core.models.video import VideoFile


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
        response = api_client.post(reverse("tournament-list"), {"name": "Incomplete"})
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


class TestArchiveAllGames:
    def test_queues_one_archive_render_per_game(self, api_client, game):
        other = baker.make("core.Game", tournament=game.tournament, files=[])

        response = api_client.post(
            reverse("tournament-archive-all-games", args=[game.tournament.pk])
        )

        assert response.status_code == 200
        assert response.data["preset"] == RenderQueueItemArchive.DEFAULT_PRESET
        assert response.data["skipped"] == []
        assert len(response.data["queued"]) == 2
        assert set(
            RenderQueueItemArchive.objects.values_list("game_id", flat=True)
        ) == {game.pk, other.pk}

    def test_skips_games_that_already_have_a_pending_archive(self, api_client, game):
        baker.make("core.Game", tournament=game.tournament, files=[])
        baker.make(
            "core.RenderQueueItemArchive",
            game=game,
            preset=RenderQueueItemArchive.DEFAULT_PRESET,
            status=RenderQueueItemArchive.Status.WAITING,
        )

        response = api_client.post(
            reverse("tournament-archive-all-games", args=[game.tournament.pk])
        )

        assert response.status_code == 200
        assert response.data["skipped"] == [game.pk]
        assert len(response.data["queued"]) == 1

    def test_force_queues_even_when_an_archive_exists(self, api_client, game):
        baker.make(
            "core.RenderQueueItemArchive",
            game=game,
            preset=RenderQueueItemArchive.DEFAULT_PRESET,
            status=RenderQueueItemArchive.Status.WAITING,
        )

        response = api_client.post(
            reverse("tournament-archive-all-games", args=[game.tournament.pk]),
            {"force": True},
        )

        assert response.status_code == 200
        assert response.data["skipped"] == []
        assert RenderQueueItemArchive.objects.filter(game=game).count() == 2

    def test_ignores_games_of_other_tournaments(self, api_client, game):
        stranger = baker.make("core.Game", files=[])

        api_client.post(
            reverse("tournament-archive-all-games", args=[game.tournament.pk])
        )

        assert not RenderQueueItemArchive.objects.filter(game=stranger).exists()


class TestGames:
    def test_returns_games_for_tournament(self, api_client, game):
        response = api_client.get(
            reverse("tournament-games", args=[game.tournament.pk])
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["name"] == game.name


class TestArchiveRefreshesVideoFiles:
    def test_repoints_video_files_at_the_archive_drive(
        self, api_client, game, tmp_path, settings, monkeypatch
    ):
        """Archiving moves the drive; the rows must follow the files."""
        archive_dir = tmp_path / "video_archive"
        settings.TOURNAMENTS_ARCHIVE_DIR = archive_dir

        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()
        video_file = VideoFile.objects.create(
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )
        stale_path = video_file.path

        # The file only exists on the archive drive, where the tournament
        # is about to resolve to.
        archived = (
            archive_dir
            / game.tournament.tournament_dir
            / "proxy"
            / video_file.expected_filename
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes(b"12345")
        monkeypatch.setattr(VideoFile, "probe_fps", staticmethod(lambda path: 50.0))

        response = api_client.post(
            reverse("tournament-archive", args=[game.tournament.pk])
        )

        assert response.status_code == 200
        assert response.data["video_files"] == {"path_fixed": 1}
        video_file.refresh_from_db()
        assert video_file.path != stale_path
        assert video_file.path == str(archived)
        assert video_file.fps == 50.0
        assert video_file.size == 5

    def test_reports_files_it_could_not_find(
        self, api_client, game, tmp_path, settings
    ):
        settings.TOURNAMENTS_ARCHIVE_DIR = tmp_path / "video_archive"
        video = baker.make("core.Video", name="proxy")
        game.video_proxy = video
        game.save(update_fields=["video_proxy"])
        video.refresh_from_db()
        VideoFile.objects.create(
            video=video,
            quality=VideoFile.Quality.LOW,
            format=VideoFile.Format.MP4,
        )

        response = api_client.post(
            reverse("tournament-archive", args=[game.tournament.pk])
        )

        assert response.data["video_files"] == {"missing": 1}
