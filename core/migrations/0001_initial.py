# Generated manually to move models into core without DB changes.

import datetime

import django.db.models.deletion
from colorfield.fields import ColorField
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    # NOTE: these CreateModel operations used to run as state-only (moving
    # models into `core` from another app that already had the tables on
    # every real deployment). That means a brand-new database never actually
    # gets these tables created, which breaks pytest-django's from-scratch
    # test DB (and any fresh install). Reused for both `database_operations`
    # and `state_operations` below so existing databases (which already have
    # 0001 recorded as applied) are unaffected, while fresh databases now
    # really get the tables created.
    _create_operations = [
                migrations.CreateModel(
                    name="Tournament",
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
                        ("name", models.CharField(max_length=100)),
                        ("short_name", models.CharField(max_length=14)),
                        ("date", models.DateField()),
                        ("place", models.CharField(default="", max_length=200)),
                        ("JTR", models.CharField(blank=True, default="", max_length=200)),
                        (
                            "tugeny_link",
                            models.CharField(blank=True, default="", max_length=200),
                        ),
                        ("color", ColorField(default="#0000")),
                        ("source_dir", models.CharField(default="-", max_length=200)),
                        ("slug", models.SlugField(default="")),
                    ],
                    options={
                        "db_table": "game_edit_tournament",
                    },
                ),
                migrations.CreateModel(
                    name="Team",
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
                        ("name", models.CharField(max_length=100)),
                        ("short_name", models.CharField(max_length=10)),
                        ("slug", models.SlugField(blank=True, default="")),
                        (
                            "image",
                            models.ImageField(
                                default="default.png", upload_to="miniatures/logos"
                            ),
                        ),
                    ],
                    options={
                        "db_table": "miniatures_team",
                    },
                ),
                migrations.CreateModel(
                    name="TmpImage",
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
                        ("name", models.CharField(max_length=100)),
                        ("date", models.DateField(auto_now_add=True)),
                        (
                            "image",
                            models.ImageField(default="default.png", upload_to="tmp"),
                        ),
                    ],
                    options={
                        "db_table": "miniatures_tmpimage",
                    },
                ),
                migrations.CreateModel(
                    name="VideoMetadata",
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
                        ("name", models.CharField(max_length=100)),
                        ("time_code", models.FloatField(default=0)),
                        ("miniature_x_offset", models.FloatField(default=0)),
                        ("miniature_y_offset", models.FloatField(default=0)),
                        ("miniature_zoom", models.FloatField(default=1)),
                        ("video_name", models.CharField(blank=True, max_length=150)),
                        ("description", models.TextField(blank=True)),
                        (
                            "publication_date",
                            models.DateTimeField(
                                blank=True, default=datetime.datetime.now
                            ),
                        ),
                        (
                            "base_image",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="base_image",
                                to="core.tmpimage",
                            ),
                        ),
                        (
                            "miniature_image",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="miniature",
                                to="core.tmpimage",
                            ),
                        ),
                        (
                            "team1",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="team1",
                                to="core.team",
                            ),
                        ),
                        (
                            "team2",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="team2",
                                to="core.team",
                            ),
                        ),
                        (
                            "tournament",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="video_metadatas",
                                to="core.tournament",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "miniatures_videometadata",
                        "unique_together": {("name", "tournament")},
                    },
                ),
                migrations.CreateModel(
                    name="Game",
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
                        ("name", models.CharField(max_length=100)),
                        ("files", models.JSONField(verbose_name="Files")),
                        ("rendered", models.CharField(blank=True, max_length=200)),
                        ("json_file", models.FileField(default="tt", upload_to="json_files")),
                        (
                            "source_proxy",
                            models.FileField(
                                blank=True, default="", upload_to="core/previews"
                            ),
                        ),
                        ("slug", models.SlugField(default="")),
                        (
                            "team1",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="game_team1",
                                to="core.team",
                            ),
                        ),
                        (
                            "team2",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="game_team2",
                                to="core.team",
                            ),
                        ),
                        (
                            "tournament",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="core.tournament",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "game_edit_game",
                    },
                ),
                migrations.CreateModel(
                    name="Cut",
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
                        ("name", models.CharField(max_length=100)),
                        (
                            "type_cut",
                            models.CharField(
                                choices=[
                                    ("MAN", "manual"),
                                    ("VID", "from video"),
                                    ("XML", "from XML"),
                                    ("ML", "from ML"),
                                    ("X", "others"),
                                ],
                                max_length=50,
                            ),
                        ),
                        (
                            "json_file",
                            models.FileField(
                                default="json_files/cuts/default.json",
                                upload_to="json_files/cuts/",
                            ),
                        ),
                        ("slug", models.SlugField(default="")),
                        (
                            "game",
                            models.ForeignKey(
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                to="core.game",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "game_edit_cut",
                    },
                ),
                migrations.CreateModel(
                    name="YTVideo",
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
                        ("title", models.CharField(default="", max_length=150)),
                        ("video_id", models.CharField(max_length=50, unique=True)),
                        (
                            "publication_date",
                            models.DateTimeField(default=datetime.date.today),
                        ),
                        ("privacy_status", models.CharField(default="", max_length=150)),
                        (
                            "linked_video",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="linked_yt_videos",
                                to="core.videometadata",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "miniatures_ytvideo",
                    },
                ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=_create_operations,
            state_operations=_create_operations,
        ),
    ]
