"""Split RenderQueueItem into Base + FFMPEG + GenCut hierarchy.

Destructive: the existing queue is cleared (user-approved). All render queue
tables are dropped and recreated with the new hierarchy.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def clear_queue(apps, schema_editor):
    """Empty all queue rows before schema changes (tables may be missing)."""
    existing = set(
        schema_editor.connection.introspection.table_names(
            schema_editor.connection.cursor()
        )
    )
    with schema_editor.connection.cursor() as cur:
        for table in (
            "game_edit_render_queue_cut",
            "game_edit_render_queue_proxy",
            "game_edit_render_queue",
        ):
            if table in existing:
                cur.execute(f"DELETE FROM {table}")


def noop_reverse(apps, schema_editor):
    """No-op reverse: data is already cleared on forward."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_alter_cut_game"),
    ]

    operations = [
        migrations.RunPython(clear_queue, noop_reverse),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "DROP TABLE IF EXISTS game_edit_render_queue_cut;\n"
                        "DROP TABLE IF EXISTS game_edit_render_queue_proxy;\n"
                        "DROP TABLE IF EXISTS game_edit_render_queue;\n"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.DeleteModel(name="RenderQueueItemCut"),
                migrations.DeleteModel(name="RenderQueueItemProxy"),
                migrations.DeleteModel(name="RenderQueueItem"),
            ],
        ),
        migrations.CreateModel(
            name="RenderQueueItemBase",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "job_type",
                    models.CharField(
                        choices=[
                            ("CUT_RENDER", "cut_render"),
                            ("GAME_PROXY", "game_proxy"),
                            ("GEN_CUT", "gen_cut"),
                        ],
                        default="CUT_RENDER",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
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
                ("pid", models.IntegerField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "game_edit_render_queue",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="RenderQueueItemBase",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "RUNNING")),
                fields=("status",),
                name="renderqueue_single_running",
            ),
        ),
        migrations.CreateModel(
            name="RenderQueueItemFFMPEG",
            fields=[
                (
                    "renderqueueitembase_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitembase",
                    ),
                ),
                ("preset", models.CharField(default="medium", max_length=10)),
                (
                    "output_filename",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("command", models.TextField(blank=True, default="")),
                (
                    "tmp_concat_file",
                    models.CharField(blank=True, default="", max_length=255),
                ),
            ],
            options={"db_table": "game_edit_render_queue_ffmpeg"},
            bases=("core.renderqueueitembase",),
        ),
        migrations.CreateModel(
            name="RenderQueueItemCut",
            fields=[
                (
                    "renderqueueitemffmpeg_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitemffmpeg",
                    ),
                ),
                (
                    "cut",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.cut",
                    ),
                ),
            ],
            options={"db_table": "game_edit_render_queue_cut"},
            bases=("core.renderqueueitemffmpeg",),
        ),
        migrations.CreateModel(
            name="RenderQueueItemProxy",
            fields=[
                (
                    "renderqueueitemffmpeg_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitemffmpeg",
                    ),
                ),
                (
                    "game",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.game",
                    ),
                ),
            ],
            options={"db_table": "game_edit_render_queue_proxy"},
            bases=("core.renderqueueitemffmpeg",),
        ),
        migrations.CreateModel(
            name="RenderQueueItemGenCut",
            fields=[
                (
                    "renderqueueitembase_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="core.renderqueueitembase",
                    ),
                ),
                ("rendered_path", models.CharField(max_length=512)),
                (
                    "tmp_dir",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                (
                    "cut",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.cut",
                    ),
                ),
            ],
            options={"db_table": "game_edit_render_queue_gen_cut"},
            bases=("core.renderqueueitembase",),
        ),
    ]
