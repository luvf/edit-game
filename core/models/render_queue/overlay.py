"""Wiring the match overlay into a cut render.

`jugger_video_manipulation` knows how to compute and draw the overlay; this
knows where a Django render gets its teams, its frame size and the picture to
blur behind the opening card. Kept apart from the queue item so that
`build_command` stays readable and this can be tested on its own.

What the match is — its teams, its condition, the score its recording starts
at — comes from the game, shared by all its cuts. A cut file with no points
produces no plan at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from jugger_video_manipulation.overlay_pipeline import (
    CutContent,
    OverlayPlan,
    RenderContext,
    build_plan,
)
from jugger_video_manipulation.overlay_render import CardText, Team
from jugger_video_manipulation.scoreboard import start_score

if TYPE_CHECKING:
    from core.models.cut import Cut
    from core.models.tournament import Team as TeamModel
    from jugger_video_manipulation.scoreboard import StartScore, Timing

#: A video dimension must stay even for the encoders in use.
EVEN = 2

#: What a render falls back to when the sources cannot be probed.
DEFAULT_SIZE = (1920, 1080)


def _probe_size(source: Path) -> tuple[int, int] | None:
    """Return a video's width and height, or None when unreadable."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(source),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= EVEN and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
    return None


def render_size(
    source: Path, scale: list[str] | None, fallback: tuple[int, int] = DEFAULT_SIZE
) -> tuple[int, int]:
    """Return the size the render will come out at.

    The overlays have to be drawn at that size, not at 1080p: a proxy preset
    scales the picture down, and an overlay drawn larger would be cropped
    rather than fitted.

    Args:
        source: a source file to measure when the preset does not decide.
        scale: the preset's scale arguments, `[width, height]`, where a `-2`
            means "whatever keeps the aspect ratio".
        fallback: used when nothing can be measured.

    Returns:
        The width and height to draw for.
    """
    measured = _probe_size(source) or fallback
    if not scale:
        return measured

    width, height = (int(value) for value in scale)
    if width > 0 and height > 0:
        return width, height
    if width > 0:
        return width, max(round(measured[1] * width / measured[0]) // EVEN * EVEN, EVEN)
    if height > 0:
        return max(
            round(measured[0] * height / measured[1]) // EVEN * EVEN, EVEN
        ), height
    return measured


#: Images that stand in for a logo a team does not have: the model's default,
#: and the placeholder several teams were given while waiting for theirs. A
#: team showing one of these gets a generated logo instead.
PLACEHOLDER_LOGOS = frozenset({"default.png", "NOPICTURE.png"})


def _logo(team: TeamModel) -> Path | None:
    """Return a team's own logo when it has one on disk, None otherwise."""
    if not team.image or Path(team.image.name).name in PLACEHOLDER_LOGOS:
        return None
    candidate = Path(team.image.path)
    return candidate if candidate.exists() else None


def teams_for(cut: Cut) -> dict[str, Team]:
    """Return the game's two teams as the overlay draws them, keyed by side.

    `team1` is the team on the left at kick-off: the game page orders them that
    way and swaps them with a button. A team without a logo on disk still gets
    its name drawn, over a generated logo.
    """
    game = cut.game
    teams: dict[str, Team] = {}
    for key, team in (("team1", game.team1), ("team2", game.team2)):
        if team is None or not team.name:
            continue
        teams[key] = Team(name=team.name, logo=_logo(team), short_name=team.short_name)
    return teams


def card_text_for(cut: Cut) -> CardText:
    """Return the words on the opening card.

    The tournament, and the winning condition written on the game — nothing
    else. The number of sets is not spelled out next to it: it is what the
    condition already says. The cut's name is not on the card either, it is an
    internal label.
    """
    game = cut.game
    return CardText(tournament=game.tournament.name, condition=game.condition or "")


def start_score_for(cut: Cut) -> StartScore | None:
    """Return the score the game's recording starts at, cleaned, or None."""
    raw = cut.game.start_score
    if not isinstance(raw, dict):
        return None
    return start_score(raw.get("team1"), raw.get("team2"))


def plan_for(
    cut: Cut,
    *,
    directory: Path,
    size: tuple[int, int],
    fps: float,
    timing: Timing | None = None,
) -> OverlayPlan:
    """Draw everything a cut file asks for, and say when each is shown.

    Args:
        cut: the cut being rendered.
        directory: where the overlay images are written.
        size: the size the render comes out at.
        fps: the frame rate the cut file counts in.
        timing: the transitions and the tail the render plays, which the
            overlays are placed on.

    Returns:
        The plan, empty when the file asks for nothing.
    """
    from jugger_video_manipulation.cut_json_parser import CutJsonParser

    points, overlays, display = CutJsonParser(cut.json_file.path).parse_all()
    if not points:
        return OverlayPlan()

    return build_plan(
        CutContent(
            points=points,
            overlays=overlays,
            display=display,
            start_score=start_score_for(cut),
        ),
        teams_for(cut),
        fps,
        directory,
        context=RenderContext(card_text=card_text_for(cut), size=size),
        timing=timing,
    )
