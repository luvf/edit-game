"""Tests for the database side of the auto-edit pipeline.

`build_catalog` answers "what can I train on" and `predictable_game` answers
"what can I run on"; the two questions have different answers, and the gap
between them is where a proposal would otherwise leak back into training.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from model_bakery import baker

from core.models.cut import Cut
from game_autoedit.data.catalog import (
    UnusableGameError,
    build_catalog,
    predictable_game,
)


@pytest.fixture()
def archived_game(game, tmp_path):
    """A game whose archive exists on disk, as the pipeline requires."""
    archive_path = tmp_path / "archive.mp4"
    archive_path.write_bytes(b"fake")
    video = baker.make("core.Video", name="archive")
    baker.make(
        "core.VideoFile",
        video=video,
        quality="archive",
        format="mp4",
        path=str(archive_path),
        fps=59.94,
    )
    game.archive_video = video
    game.save(update_fields=["archive_video"])
    return game


def _cut_with_points(game, type_cut: str, points: int = 2) -> Cut:
    """Create a cut carrying real points, so the catalog accepts it."""
    cut = Cut.objects.create(game=game, name=type_cut, type_cut=type_cut)
    cut.set_json(
        {
            "points": [
                {"in": 100 * i, "out": 100 * i + 50} for i in range(1, points + 1)
            ],
            "overlays": [],
        }
    )
    return cut


class TestProposalsAreNeverTrainingMaterial:
    def test_a_game_labelled_only_by_the_model_is_rejected(self, archived_game):
        _cut_with_points(archived_game, "ML")

        catalog = build_catalog()

        assert catalog.games == []
        assert [r.reason for r in catalog.rejected] == ["aucun cut humain"]

    def test_a_human_cut_still_wins_when_a_proposal_sits_next_to_it(
        self, archived_game
    ):
        _cut_with_points(archived_game, "ML")
        human = _cut_with_points(archived_game, "MAN")

        catalog = build_catalog()

        assert [entry.cut_id for entry in catalog.games] == [human.pk]

    def test_an_unlabelled_game_is_still_predictable(self, archived_game):
        catalog = build_catalog()
        assert catalog.games == []

        target = predictable_game(archived_game.pk)

        assert target.game_id == archived_game.pk
        assert target.audio_source.exists()
        assert target.fps == pytest.approx(59.94)


class TestPredictableGame:
    def test_records_the_cut_the_proposal_belongs_to(self, archived_game):
        cut = _cut_with_points(archived_game, "ML", points=0)

        target = predictable_game(archived_game.pk, cut_id=cut.pk)

        assert target.cut_id == cut.pk
        assert target.cut_json_path == Path(cut.json_file.path)

    def test_an_empty_cut_file_is_not_a_reason_to_refuse(self, archived_game):
        cut = Cut.objects.create(game=archived_game, name="vide", type_cut="ML")
        cut.json_file.save(
            "empty.json",
            ContentFile(json.dumps({"points": [], "overlays": []}).encode()),
            save=True,
        )

        assert predictable_game(archived_game.pk, cut_id=cut.pk).cut_id == cut.pk

    def test_a_game_without_an_archive_says_what_to_do(self, game):
        with pytest.raises(UnusableGameError, match="archive"):
            predictable_game(game.pk)

    def test_an_unknown_game_is_reported_as_such(self, db):
        with pytest.raises(UnusableGameError, match="introuvable"):
            predictable_game(123456)
