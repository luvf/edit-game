"""Remove proxy_file field from Game."""

from django.db import migrations


class Migration(migrations.Migration):
    """Remove proxy_file from Game."""

    dependencies = [
        ("core", "0012_render_queue_remove_command"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="game",
            name="proxy_file",
        ),
    ]
