"""Move cut/game relations to render queue subclasses."""

from django.db import migrations, models
import django.db.models.deletion


def move_relations(apps, schema_editor) -> None:
    """Copy cut/game ids from base table into subclass tables."""
    cursor = schema_editor.connection.cursor()
    base_table = "game_edit_render_queue"
    cut_table = "game_edit_render_queue_cut"
    proxy_table = "game_edit_render_queue_proxy"

    cursor.execute(
        f"""
        SELECT id, cut_id
        FROM {base_table}
        WHERE job_type = 'CUT_RENDER' AND cut_id IS NOT NULL
        """
    )
    cut_rows = cursor.fetchall()
    if cut_rows:
        cursor.executemany(
            f"UPDATE {cut_table} SET cut_id = ? WHERE renderqueueitem_ptr_id = ?",
            [(cut_id, item_id) for item_id, cut_id in cut_rows],
        )

    cursor.execute(
        f"""
        SELECT id, game_id
        FROM {base_table}
        WHERE job_type = 'GAME_PROXY' AND game_id IS NOT NULL
        """
    )
    proxy_rows = cursor.fetchall()
    if proxy_rows:
        cursor.executemany(
            f"UPDATE {proxy_table} SET game_id = ? WHERE renderqueueitem_ptr_id = ?",
            [(game_id, item_id) for item_id, game_id in proxy_rows],
        )


class Migration(migrations.Migration):
    """Move cut/game relations to render queue subclasses."""

    dependencies = [
        ("core", "0010_render_queue_item_subclasses"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE game_edit_render_queue_cut ADD COLUMN cut_id integer",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "ALTER TABLE game_edit_render_queue_proxy ADD COLUMN game_id integer",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunPython(move_relations, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="renderqueueitem",
                    name="cut",
                ),
                migrations.RemoveField(
                    model_name="renderqueueitem",
                    name="game",
                ),
                migrations.AddField(
                    model_name="renderqueueitemcut",
                    name="cut",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.cut",
                    ),
                ),
                migrations.AddField(
                    model_name="renderqueueitemproxy",
                    name="game",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.game",
                    ),
                ),
            ],
        ),
    ]
