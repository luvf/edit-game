"""Tests for the /api/tournaments/ endpoints."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils.text import slugify
from model_bakery import baker
from PIL import Image

from core.models.media import VideoMetadata
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

    def test_counts_the_high_quality_renders_on_disk(self, api_client, game, tmp_path):
        def render(quality, *, on_disk=True):
            cut = baker.make("core.Cut", game=game, type_cut="MAN")
            cut.rendered_video = baker.make("core.Video", name=f"cut{cut.pk}")
            cut.save(update_fields=["rendered_video"])
            path = tmp_path / f"cut{cut.pk}_{quality}.mp4"
            if on_disk:
                path.write_bytes(b"mp4")
            VideoFile.objects.create(
                video=cut.rendered_video, quality=quality, path=str(path)
            )

        render("high")
        render("high_av1")
        render("medium")
        # Queued or failed: the row exists, the file does not.
        render("high", on_disk=False)

        response = api_client.get(
            reverse("tournament-games", args=[game.tournament.pk])
        )

        assert response.data[0]["high_renders"] == 2


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


class TestSyncVideos:
    @pytest.fixture(autouse=True)
    def _no_media_io(self, monkeypatch):
        monkeypatch.setattr("core.models.media.get_chapters", lambda video_file: [])
        monkeypatch.setattr(
            "core.models.media.get_frame", lambda path, tc: Image.new("RGB", (20, 10))
        )
        monkeypatch.setattr(
            "core.models.media.generate_miniature",
            lambda **kwargs: Image.new("RGB", (20, 10)),
        )

    @staticmethod
    def _put_proxy_on_disk(game, tmp_path):
        game.video_proxy = baker.make("core.Video", name=f"proxy{game.pk}")
        game.save(update_fields=["video_proxy"])
        path = tmp_path / f"proxy{game.pk}_low.mp4"
        path.write_bytes(b"mp4")
        VideoFile.objects.create(video=game.video_proxy, quality="low", path=str(path))

    @staticmethod
    def _sync(api_client, tournament):
        return api_client.post(reverse("tournament-sync-videos", args=[tournament.pk]))

    def test_creates_the_metadata_of_a_game_with_a_video(
        self, api_client, game, tmp_path
    ):
        self._put_proxy_on_disk(game, tmp_path)

        response = self._sync(api_client, game.tournament)

        assert response.status_code == 200
        assert response.data["created"] == [game.name]
        game.refresh_from_db()
        vm = game.video_metadata
        assert (vm.team1, vm.team2) == (game.team1, game.team2)
        assert vm.miniature_image is not None

    def test_does_not_duplicate_on_a_second_sync(self, api_client, game, tmp_path):
        self._put_proxy_on_disk(game, tmp_path)

        self._sync(api_client, game.tournament)
        response = self._sync(api_client, game.tournament)

        assert response.data["created"] == []
        assert VideoMetadata.objects.count() == 1

    def test_skips_games_without_video_or_teams(
        self, api_client, game, tournament, tmp_path
    ):
        no_teams = baker.make(
            "core.Game", tournament=tournament, team1=None, team2=None, files=[]
        )
        self._put_proxy_on_disk(no_teams, tmp_path)

        response = self._sync(api_client, tournament)

        assert response.data["created"] == []
        assert response.data["skipped"] == [
            {"game": game.name, "reason": "no video on disk"},
            {"game": no_teams.name, "reason": "teams not set"},
        ]
        assert not VideoMetadata.objects.exists()

    def test_adopts_an_orphan_of_the_same_name(self, api_client, game, tmp_path):
        self._put_proxy_on_disk(game, tmp_path)
        orphan = VideoMetadata(
            name=game.name,
            tournament=game.tournament,
            team1=game.team1,
            team2=game.team2,
        )
        orphan.save()

        response = self._sync(api_client, game.tournament)

        assert response.data["created"] == []
        game.refresh_from_db()
        assert game.video_metadata == orphan

    def test_leaves_other_orphans_alone(self, api_client, game, tournament):
        orphan = VideoMetadata(
            name="old_render.mp4",
            tournament=tournament,
            team1=game.team1,
            team2=game.team2,
        )
        orphan.save()

        response = self._sync(api_client, tournament)

        assert response.status_code == 200
        assert [video["pk"] for video in response.data["videos"]] == [orphan.pk]
