"""Tests for what a Django render takes from the game."""

from __future__ import annotations

from django.core.files.base import ContentFile

from core.models.cut import Cut
from core.models.render_queue.overlay import (
    card_text_for,
    start_score_for,
    teams_for,
)


def _cut(game, name="ML 2026-09-13 v3"):
    """A cut whose name is the internal label an editor never wants on screen."""
    return Cut.objects.create(game=game, name=name, type_cut="MAN")


class TestCardText:
    def test_the_tournament_is_named(self, game):
        assert card_text_for(_cut(game)).tournament == game.tournament.name

    def test_the_cut_name_never_reaches_the_card(self, game):
        game.condition = "BO3"
        game.save()

        text = card_text_for(_cut(game))

        assert "ML 2026-09-13 v3" not in (text.tournament, text.condition)

    def test_the_condition_is_the_game_s(self, game):
        game.condition = "2 sets gagnants, mort subite"
        game.sets_to_win = 2
        game.save()

        # The number of sets is not spelled out next to it.
        assert card_text_for(_cut(game)).condition == "2 sets gagnants, mort subite"

    def test_without_a_condition_the_card_carries_only_the_tournament(self, game):
        text = card_text_for(_cut(game))

        assert text.condition == ""
        assert text.tournament == game.tournament.name


class TestTeamsFor:
    def test_the_game_s_teams_are_drawn_in_its_order(self, game):
        teams = teams_for(_cut(game))

        assert (teams["team1"].name, teams["team2"].name) == ("Alpha", "Beta")

    def test_swapping_the_game_s_teams_swaps_the_sides(self, game):
        game.team1, game.team2 = game.team2, game.team1
        game.save()

        teams = teams_for(_cut(game))

        assert teams["team1"].name == "Beta"

    def test_a_missing_team_is_left_out(self, game):
        game.team2 = None
        game.save()

        assert set(teams_for(_cut(game))) == {"team1"}

    def test_the_short_name_travels_with_the_team(self, game):
        assert teams_for(_cut(game))["team1"].short_name == "ALP"


class TestPlaceholderLogos:
    def test_the_shared_placeholder_is_no_logo(self, game):
        # "noLogo" and the others waiting for theirs all share NOPICTURE.png:
        # they get a generated logo, not the placeholder.
        game.team1.image.save("NOPICTURE.png", ContentFile(b"png"), save=True)

        assert teams_for(_cut(game))["team1"].logo is None

    def test_a_real_logo_is_used(self, game):
        game.team1.image.save("ALP.png", ContentFile(b"png"), save=True)

        assert teams_for(_cut(game))["team1"].logo.name == "ALP.png"


class TestStartScoreFor:
    def test_none_when_the_game_has_none(self, game):
        assert start_score_for(_cut(game)) is None

    def test_the_game_s_score_is_padded(self, game):
        game.start_score = {"team1": [10, 3], "team2": [8]}
        game.save()

        assert start_score_for(_cut(game)) == {"team1": [10, 3], "team2": [8, 0]}
