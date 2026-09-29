"""Add pid to RenderQueueItem."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_render_queue_item"),
    ]

    operations = [
        migrations.AddField(
            model_name="renderqueueitem",
            name="pid",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
