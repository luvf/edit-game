"""Require game/cut on render queue subclasses."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Require game/cut on render queue subclasses."""

    dependencies = [
        ("core", "0013_remove_game_proxy_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="renderqueueitemcut",
            name="cut",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="core.cut",
            ),
        ),
        migrations.AlterField(
            model_name="renderqueueitemproxy",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="core.game",
            ),
        ),
    ]
