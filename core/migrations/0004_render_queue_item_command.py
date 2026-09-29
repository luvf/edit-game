"""Add command field to render queue items."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add command field to render queue items."""

    dependencies = [
        ("core", "0003_render_queue_item_proxy"),
    ]

    operations = [
        migrations.AddField(
            model_name="renderqueueitem",
            name="command",
            field=models.TextField(blank=True, default=""),
        ),
    ]
