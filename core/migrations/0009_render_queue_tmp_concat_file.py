"""Add tmp concat file tracking to render queue items."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add tmp_concat_file to render queue items."""

    dependencies = [
        ("core", "0008_render_queue_created_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="renderqueueitem",
            name="tmp_concat_file",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
