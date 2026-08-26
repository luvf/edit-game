"""Merge render queue migrations so pid is always applied."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Merge render queue migrations."""

    dependencies = [
        ("core", "0003_render_queue_pid"),
        ("core", "0004_render_queue_item_command"),
    ]

    operations = []
