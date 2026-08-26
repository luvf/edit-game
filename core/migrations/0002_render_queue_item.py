"""Create RenderQueueItem model."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Add render queue model."""

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RenderQueueItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("preset", models.CharField(default="medium", max_length=10)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "pending"),
                            ("RUNNING", "running"),
                            ("DONE", "done"),
                            ("FAILED", "failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("output_filename", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "cut",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="core.cut"
                    ),
                ),
            ],
            options={
                "db_table": "game_edit_render_queue",
                "ordering": ["created_at"],
            },
        ),
    ]
