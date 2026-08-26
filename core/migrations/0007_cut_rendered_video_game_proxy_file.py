"""Add rendered video and proxy file paths."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add rendered_video for Cut and proxy_file for Game."""

    dependencies = [
        ("core", "0006_render_queue_single_running"),
    ]

    operations = [
        migrations.AddField(
            model_name="game",
            name="proxy_file",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cut",
            name="rendered_video",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
