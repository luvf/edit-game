"""Tests for game_autoedit.datasets.splits."""

from __future__ import annotations

from pathlib import Path

import pytest

from game_autoedit.data.catalog import LabeledGame
from game_autoedit.datasets.splits import SplitSpec, make_split


def game(game_id, tournament):
    return LabeledGame(
        game_id=game_id,
        name=f"game {game_id}",
        slug=f"game-{game_id}",
        tournament=tournament,
        cut_id=game_id,
        cut_type="VID",
        cut_json_path=Path(f"/tmp/cut_{game_id}.json"),
        audio_source=Path(f"/tmp/game_{game_id}.mp4"),
        fps=59.94,
    )


def catalog(counts):
    games = []
    game_id = 0
    for tournament, count in counts.items():
        for _ in range(count):
            game_id += 1
            games.append(game(game_id, tournament))
    return games


class TestMakeSplit:
    def test_partitions_are_disjoint_and_complete(self):
        games = catalog({"A": 10, "B": 10})
        split = make_split(games, SplitSpec(seed=0))

        ids = [g.game_id for g in split.train + split.val + split.test]
        assert sorted(ids) == [g.game_id for g in games]
        assert len(set(ids)) == len(ids)

    def test_fractions_are_respected(self):
        split = make_split(
            catalog({"A": 100}), SplitSpec(val_fraction=0.2, test_fraction=0.1)
        )

        assert len(split.val) == 20
        assert len(split.test) == 10
        assert len(split.train) == 70

    def test_same_seed_gives_the_same_partition(self):
        games = catalog({"A": 20})
        first = make_split(games, SplitSpec(seed=7))
        second = make_split(games, SplitSpec(seed=7))

        assert [g.game_id for g in first.train] == [g.game_id for g in second.train]

    def test_different_seed_changes_the_partition(self):
        games = catalog({"A": 40})
        first = make_split(games, SplitSpec(seed=1))
        second = make_split(games, SplitSpec(seed=2))

        assert [g.game_id for g in first.val] != [g.game_id for g in second.val]

    def test_holdout_tournament_becomes_the_test_set(self):
        split = make_split(
            catalog({"A": 10, "B": 6}), SplitSpec(holdout_tournaments=("B",))
        )

        assert split.tournaments("test") == ["B"]
        assert len(split.test) == 6
        assert "B" not in split.tournaments("train")
        assert "B" not in split.tournaments("val")

    def test_several_holdout_tournaments(self):
        split = make_split(
            catalog({"A": 10, "B": 6, "C": 4}),
            SplitSpec(holdout_tournaments=("B", "C")),
        )

        assert split.tournaments("test") == ["B", "C"]
        assert len(split.test) == 10

    def test_unknown_holdout_tournament_raises(self):
        with pytest.raises(ValueError, match="tournoi"):
            make_split(catalog({"A": 4}), SplitSpec(holdout_tournaments=("Z",)))

    def test_group_by_tournament_keeps_tournaments_together(self):
        games = catalog({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})
        split = make_split(games, SplitSpec(group_by="tournament", seed=0))

        train = set(split.tournaments("train"))
        assert not train & set(split.tournaments("val"))
        assert not train & set(split.tournaments("test"))

    def test_tiny_catalog_keeps_a_training_game(self):
        split = make_split(catalog({"A": 2}), SplitSpec())

        assert len(split.train) >= 1
