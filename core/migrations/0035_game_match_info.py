"""Move what a match is from its cut files onto the game.

The teams already lived on the game. The condition, the number of sets and
the score a recording starts at were typed into a GameInfo block in each cut
file; they now belong to the game, shared by all of its cuts. What the cut
files already say is copied over, the first cut that says it winning, and a
value already on the game is never overwritten. The files are left alone: the
block is ignored when read, and dropped the next time the editor saves.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.db import migrations, models

GAME_INFO_TYPES = ("GameInfo", "TeamIntroduction")


def _game_info(cut):
    try:
        path = Path(cut.json_file.path)
        data = json.loads(path.read_text())
    except (OSError, ValueError, NotImplementedError):
        return None
    for item in data.get("overlays") or []:
        if isinstance(item, dict) and item.get("type") in GAME_INFO_TYPES:
            return item
    return None


def _start_score(raw):
    from jugger_video_manipulation.scoreboard import start_score

    if not isinstance(raw, dict):
        return None
    return start_score(raw.get("team1"), raw.get("team2"))


def copy_match_info(apps, schema_editor):
    _ = schema_editor
    game_model = apps.get_model("core", "Game")
    cut_model = apps.get_model("core", "Cut")
    for game in game_model.objects.all():
        changed = []
        for cut in cut_model.objects.filter(game=game).order_by("pk"):
            info = _game_info(cut)
            if info is None:
                continue
            condition = str(info.get("condition") or "").strip()
            if condition and not game.condition:
                game.condition = condition[:200]
                changed.append("condition")
            try:
                sets = int(info.get("sets_to_win"))
            except (TypeError, ValueError):
                sets = 0
            if sets > 0 and game.sets_to_win is None:
                game.sets_to_win = sets
                changed.append("sets_to_win")
            start = _start_score(info.get("start_score"))
            if start and game.start_score is None:
                game.start_score = start
                changed.append("start_score")
        if changed:
            game.save(update_fields=sorted(set(changed)))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_cut_curves_file_alter_renderqueueitembase_job_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="game",
            name="condition",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Condition de victoire, en texte libre, affichée sur la carte d'ouverture.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="sets_to_win",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="game",
            name="start_score",
            field=models.JSONField(
                blank=True,
                help_text=(
                    "Score quand l'enregistrement commence, pour un match déjà en cours : "
                    '{"team1": [10, 3], "team2": [8, 0]}, un nombre par set, le dernier '
                    "étant le set en cours."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(copy_match_info, migrations.RunPython.noop),
    ]
