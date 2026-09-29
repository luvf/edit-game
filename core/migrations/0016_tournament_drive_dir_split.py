from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def split_source_dir(apps, schema_editor) -> None:
    Tournament = apps.get_model("core", "Tournament")
    base_dir = getattr(settings, "TOURNAMENTS_BASE_DIR", Path("/mnt/video/juggerData/tournois"))
    base_dir_str = str(base_dir)

    for tournament in Tournament.objects.all():
        source_dir = getattr(tournament, "source_dir", "") or ""
        if source_dir in {"", "-"}:
            tournament.drive_dir = base_dir_str
            tournament.tournament_dir = ""
            tournament.save(update_fields=["drive_dir", "tournament_dir"])
            continue

        path = Path(source_dir)
        tournament.tournament_dir = path.name
        parent = path.parent
        if str(parent) == ".":
            tournament.drive_dir = base_dir_str
        else:
            tournament.drive_dir = str(parent)
        tournament.save(update_fields=["drive_dir", "tournament_dir"])


def noop_reverse(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_render_queue_add_command"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="drive_dir",
            field=models.CharField(
                default=str(settings.TOURNAMENTS_BASE_DIR), max_length=200
            ),
        ),
        migrations.AddField(
            model_name="tournament",
            name="tournament_dir",
            field=models.CharField(default="", max_length=200, blank=True),
        ),
        migrations.RunPython(split_source_dir, reverse_code=noop_reverse),
        migrations.RemoveField(
            model_name="tournament",
            name="source_dir",
        ),
    ]
