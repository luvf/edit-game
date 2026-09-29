"""Add command field back to RenderQueueItem."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add command to render queue items."""

    dependencies = [
        ("core", "0014_render_queue_require_relations"),
    ]

    operations = [
        migrations.AddField(
            model_name="renderqueueitem",
            name="command",
            field=models.TextField(blank=True, default=""),
        ),
    ]
