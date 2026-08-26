"""Remove render queue command field."""

from django.db import migrations


class Migration(migrations.Migration):
    """Remove command from render queue items."""

    dependencies = [
        ("core", "0011_render_queue_item_move_relations"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="renderqueueitem",
            name="command",
        ),
    ]
