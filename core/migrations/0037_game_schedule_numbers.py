"""Number the games as the schedule does, and give them a short win condition.

A game gets its terrain, its day and its place in that day, which together
make its number TTJGG, and a win condition as a short code like `1a10+2v`.
Both name its renders.

Games were already named after them by hand, as in `8205 blue fangs vs mh
1a10+2v`: a one- or two-digit terrain, a digit for the day, two for the
game, and the condition as the last word. Those names are read to fill the
new fields. A name that does not start that way is left at zeros, and so is
one made of a number alone, like `1014`: nothing says it is a schedule
number.
"""

from __future__ import annotations

import re

import django.core.validators
from django.db import migrations, models


SCHEDULE_NAME = re.compile(r"^(\d{1,2})(\d)(\d{2})\s+(.*?)\s*$")
WIN_CONDITION = re.compile(r"(?:^|\s)(\d+a\d+\S*)$")


def parse_schedule(name):
    """Read `(terrain, day, game, win condition)` off a game's name, or None."""
    match = SCHEDULE_NAME.match(name)
    if match is None:
        return None
    terrain, day, game, rest = match.groups()
    condition = WIN_CONDITION.search(rest)
    return (
        int(terrain),
        int(day),
        int(game),
        condition.group(1)[:30] if condition else "",
    )


def fill_schedule(apps, schema_editor):
    _ = schema_editor
    game_model = apps.get_model("core", "Game")
    for game in game_model.objects.all():
        parsed = parse_schedule(game.name)
        if parsed is None:
            continue
        game.field_number, game.day_number, game.game_number, game.win_condition = (
            parsed
        )
        game.save(
            update_fields=["field_number", "day_number", "game_number", "win_condition"]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0036_game_video_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="game",
            name="day_number",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Numéro de jour, sur 1 chiffre.",
                validators=[django.core.validators.MaxValueValidator(9)],
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="field_number",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Numéro de terrain, sur 2 chiffres.",
                validators=[django.core.validators.MaxValueValidator(99)],
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="game_number",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Numéro de la game dans la journée, sur 2 chiffres.",
                validators=[django.core.validators.MaxValueValidator(99)],
            ),
        ),
        migrations.AddField(
            model_name="game",
            name="win_condition",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Condition de victoire en code court, comme 1a10+2v : elle entre dans le nom des rendus.",
                max_length=30,
            ),
        ),
        migrations.RunPython(fill_schedule, migrations.RunPython.noop),
    ]
