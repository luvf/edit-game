"""Admin panel for game_edit app."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib import admin

from game_edit.models import Cut, Game, Team, Tournament

# Register your models here.


type ListDisplay = list[Any] | tuple[Any, ...]

if TYPE_CHECKING:  # proposed by AI
    TournamentAdminBase = admin.ModelAdmin[Tournament]
    GameAdminBase = admin.ModelAdmin[Game]
    TeamAdminBase = admin.ModelAdmin[Team]
else:
    TournamentAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    GameAdminBase = admin.ModelAdmin  # type: ignore[assignment]
    TeamAdminBase = admin.ModelAdmin  # type: ignore[assignment]


@admin.register(Tournament)
class TournamentAdmin(TournamentAdminBase):
    """tournament admin panel."""

    list_display: ClassVar[ListDisplay] = (  # type: ignore[misc]
        "name",
        "short_name",
        "place",
        "date",
        "JTR",
        "tugeny_link",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}


@admin.register(Game)
class GameAdmin(GameAdminBase):
    """game admin panel."""

    list_display: ClassVar[ListDisplay] = (  # type: ignore[misc]
        "name",
        "tournament",
        "team1",
        "team2",
        "rendered",
        "json_file",
    )
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}


@admin.register(Team)
class TeamAdmin(TeamAdminBase):
    """team admin panel."""

    list_display: ClassVar[ListDisplay] = ("name", "logo")  # type: ignore[misc]
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ["name"]}


admin.site.register(Cut)
