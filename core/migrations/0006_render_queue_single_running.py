"""Ensure only one render queue item can be running at a time."""

from django.db import migrations, models
from django.db.models import Q


def normalize_running_queue_items(apps, schema_editor) -> None:
    """Keep only the oldest RUNNING item; move others to WAITING."""
    _ = schema_editor
    render_queue_item = apps.get_model("core", "RenderQueueItem")
    running_items = render_queue_item.objects.filter(status="RUNNING").order_by(
        "created_at"
    )
    first = running_items.first()
    if not first:
        return
    (
        running_items.exclude(pk=first.pk).update(status="WAITING", started_at=None)
    )


class Migration(migrations.Migration):
    """Add uniqueness constraint for running render queue items."""

    dependencies = [
        ("core", "0005_render_queue_pid"),
    ]

    operations = [
        migrations.RunPython(
            normalize_running_queue_items, migrations.RunPython.noop
        ),
        migrations.AddConstraint(
            model_name="renderqueueitem",
            constraint=models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="RUNNING"),
                name="renderqueue_single_running",
            ),
        ),
    ]
