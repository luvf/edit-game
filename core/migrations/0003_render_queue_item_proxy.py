"""Add job type and game target to render queue items."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_render_queue_item"),
    ]

    operations = [
        migrations.AddField(
            model_name="renderqueueitem",
            name="game",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="core.game",
            ),
        ),
        migrations.AddField(
            model_name="renderqueueitem",
            name="job_type",
            field=models.CharField(
                choices=[("CUT_RENDER", "cut_render"), ("GAME_PROXY", "game_proxy")],
                default="CUT_RENDER",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="renderqueueitem",
            name="cut",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="core.cut",
            ),
        ),
    ]
