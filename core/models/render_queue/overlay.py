"""Wiring the match overlay into a cut render.

`jugger_video_manipulation` knows how to compute and draw the overlay; this
knows where a Django render gets its teams, its frame size and the picture to
blur behind the opening card. Kept apart from the queue item so that
`build_command` stays readable and this can be tested on its own.

A cut file with no `match` block and no overlays produces no plan at all, so
every cut that exists today renders exactly as it does today.
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

if TYPE_CHECKING:
    from PIL import Image

    from core.models.cut import Cut

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


def first_frame(
    source: Path, at_frame: int, fps: float, target: Path
) -> Image.Image | None:
    """Grab one frame of the rushes, to blur behind the opening card.

    Returns None rather than raising when the grab fails: a missing background
    costs a flat card, not a failed render.
    """
    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{at_frame / fps:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(target),
            "-y",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0 or not target.exists():
        return None
    return Image.open(target)


def teams_for(cut: Cut) -> dict[str, Team]:
    """Return the game's two teams, keyed as the match block names them.

    A team without a logo on disk still gets its name drawn; the overlay
    simply leaves the logo out rather than failing.
    """
    game = cut.game
    teams: dict[str, Team] = {}
    for key, team in (("team1", game.team1), ("team2", game.team2)):
        if team is None:
            continue
        logo: Path | None = None
        if team.image:
            candidate = Path(team.image.path)
            logo = candidate if candidate.exists() else None
        teams[key] = Team(name=team.name, logo=logo)
    return teams


def card_text_for(cut: Cut) -> CardText:
    """Return the words on the opening card, taken from the game itself."""
    tournament = cut.game.tournament
    condition = ""
    winning = (cut.get_json().get("match") or {}).get("winning_condition") or {}
    if winning.get("type") == "sets" and winning.get("sets_to_win"):
        condition = f"{winning['sets_to_win']} sets gagnants"
    return CardText(tournament=tournament.name, stage=cut.name, condition=condition)


def plan_for(
    cut: Cut,
    *,
    directory: Path,
    source: Path,
    size: tuple[int, int],
    fps: float,
) -> OverlayPlan:
    """Draw everything a cut file asks for, and say when each is shown.

    Args:
        cut: the cut being rendered.
        directory: where the overlay images are written.
        source: a rush, used to grab the picture behind the opening card.
        size: the size the render comes out at.
        fps: the frame rate the cut file counts in.

    Returns:
        The plan, empty when the file asks for nothing.
    """
    from jugger_video_manipulation.cut_json_parser import CutJsonParser

    points, overlays, match, display = CutJsonParser(cut.json_file.path).parse_all()
    if not match and not overlays:
        return OverlayPlan()

    background = None
    if any(item.get("type") == "TeamIntroduction" for item in overlays):
        at_frame = points[0]["in"] if points else 0
        background = first_frame(source, at_frame, fps, directory / "background.png")

    return build_plan(
        CutContent(points=points, overlays=overlays, match=match, display=display),
        teams_for(cut),
        fps,
        directory,
        context=RenderContext(
            background=background, card_text=card_text_for(cut), size=size
        ),
    )
