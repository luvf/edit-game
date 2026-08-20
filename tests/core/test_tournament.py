"""Tests for core.models.tournament (Tournament media paths, Team.identify_team)."""

from __future__ import annotations

from pathlib import Path

from model_bakery import baker

from core.models.tournament import Team


class TestMediaPath:
    def test_media_path_joins_drive_and_tournament_dir(self, tournament):
        assert tournament.media_path == Path(tournament.drive_dir) / tournament.tournament_dir


class TestTournamentMediaUrl:
    def test_non_archive_tournament_uses_local_url(self, tournament):
        assert tournament.tournament_media_url.startswith("http://127.0.0.1:8081/tournois/")
        assert tournament.tournament_media_url.endswith(tournament.tournament_dir)

    def test_archived_tournament_uses_archive_url(self, tournament, settings):
        tournament.drive_dir = str(settings.TOURNAMENTS_ARCHIVE_DIR)
        tournament.save(update_fields=["drive_dir"])

        assert tournament.tournament_media_url.startswith("http://192.168.1.2:8001/tournois/")


class TestIdentifyTeam:
    def test_no_teams_in_db_returns_none_pair(self, db):
        assert Team.identify_team("whatever.mp4") == (None, None)

    def test_two_matches_ordered_by_short_name_length(self, db):
        short = baker.make("core.Team", name="Juggernauts", short_name="JUG")
        long_ = baker.make("core.Team", name="Bears", short_name="BEAR")

        result = Team.identify_team("match_JUG_vs_BEAR.mp4")

        assert result == (long_, short)

    def test_single_match_falls_back_to_first_team(self, db):
        team_a = baker.make("core.Team", name="Alpha", short_name="ALP")
        team_b = baker.make("core.Team", name="Zulu", short_name="ZUL")

        result = Team.identify_team("clip_ZUL_only.mp4")

        assert result == (team_b, team_a)


class TestGetRenderedPath:
    def test_default_subdir(self, tournament):
        assert tournament.get_rendered_path() == tournament.media_path / "rendered"

    def test_custom_subdir(self, tournament):
        assert tournament.get_rendered_path(Path("custom")) == (
            tournament.media_path / "custom"
        )


class TestArchive:
    def test_sets_drive_dir_to_archive_dir(self, tournament, settings):
        tournament.archive()

        assert tournament.drive_dir == str(settings.TOURNAMENTS_ARCHIVE_DIR)
        tournament.refresh_from_db()
        assert tournament.drive_dir == str(settings.TOURNAMENTS_ARCHIVE_DIR)


class TestGenerateGames:
    def test_creates_games_grouped_by_video_id_sorted_by_segment(self, tournament):
        rushs_dir = tournament.media_path / "rushs"
        rushs_dir.mkdir(parents=True, exist_ok=True)
        (rushs_dir / "GH020575.MP4").touch()
        (rushs_dir / "GH010575.MP4").touch()
        (rushs_dir / "GX010576.MP4").touch()
        (rushs_dir / "not_matching.MP4").touch()
        (rushs_dir / "GH010575.txt").touch()

        games = tournament.generate_games()

        assert len(games) == 2
        game_575 = next(g for g in games if g.name == "575")
        assert game_575.files == ["GH010575.MP4", "GH020575.MP4"]
        game_576 = next(g for g in games if g.name == "576")
        assert game_576.files == ["GX010576.MP4"]

    def test_does_not_recreate_existing_games(self, tournament):
        rushs_dir = tournament.media_path / "rushs"
        rushs_dir.mkdir(parents=True, exist_ok=True)
        (rushs_dir / "GH010575.MP4").touch()

        first_batch = tournament.generate_games()
        assert len(first_batch) == 1

        second_batch = tournament.generate_games()

        assert second_batch == []
