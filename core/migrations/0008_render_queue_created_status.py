"""Rename render queue pending status to created."""

from django.db import migrations, models


def migrate_pending_to_created(apps, schema_editor) -> None:
    _ = schema_editor
    render_queue_item = apps.get_model("core", "RenderQueueItem")
    render_queue_item.objects.filter(status="PENDING").update(status="CREATED")


class Migration(migrations.Migration):
    """Rename pending to created in render queue."""

    dependencies = [
        ("core", "0007_cut_rendered_video_game_proxy_file"),
    ]

    operations = [
        migrations.RunPython(migrate_pending_to_created, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="renderqueueitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("CREATED", "created"),
                    ("WAITING", "waiting"),
                    ("RUNNING", "running"),
                    ("DONE", "done"),
                    ("FAILED", "failed"),
                ],
                default="CREATED",
                max_length=20,
            ),
        ),
    ]
