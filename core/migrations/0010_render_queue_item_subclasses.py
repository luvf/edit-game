"""Add render queue item subclasses."""

from django.db import migrations, models
import django.db.models.deletion


def create_subclass_rows(apps, schema_editor) -> None:
    _ = schema_editor
    RenderQueueItem = apps.get_model("core", "RenderQueueItem")
    RenderQueueItemCut = apps.get_model("core", "RenderQueueItemCut")
    RenderQueueItemProxy = apps.get_model("core", "RenderQueueItemProxy")

    for item in RenderQueueItem.objects.all().iterator():
        if item.job_type == "CUT_RENDER":
            if not RenderQueueItemCut.objects.filter(
                renderqueueitem_ptr_id=item.pk
            ).exists():
                RenderQueueItemCut.objects.create(renderqueueitem_ptr_id=item.pk)
        elif item.job_type == "GAME_PROXY":
            if not RenderQueueItemProxy.objects.filter(
                renderqueueitem_ptr_id=item.pk
            ).exists():
                RenderQueueItemProxy.objects.create(renderqueueitem_ptr_id=item.pk)


class Migration(migrations.Migration):
    """Add render queue item subclasses."""

    dependencies = [
        ("core", "0009_render_queue_tmp_concat_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="RenderQueueItemCut",
            fields=[
                (
                    "renderqueueitem_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitem",
                    ),
                ),
            ],
            bases=("core.renderqueueitem",),
            options={
                "db_table": "game_edit_render_queue_cut",
            },
        ),
        migrations.CreateModel(
            name="RenderQueueItemProxy",
            fields=[
                (
                    "renderqueueitem_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitem",
                    ),
                ),
            ],
            bases=("core.renderqueueitem",),
            options={
                "db_table": "game_edit_render_queue_proxy",
            },
        ),
        migrations.RunPython(create_subclass_rows, migrations.RunPython.noop),
    ]
