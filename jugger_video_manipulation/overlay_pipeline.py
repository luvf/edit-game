"""Turning a cut file into the images and windows a render needs.

This is the join between the three pieces that already exist: the parser reads
the file, `scoreboard` says what the board shows and when, `overlay_render`
draws it. Here each state becomes a PNG on disk and a window in seconds of the
finished render, which is exactly what `filter_overlay` consumes.

The opening card is handled apart, because it is not an overlay: it goes in
front of the match rather than over it, so it lengthens the render and pushes
everything else back by its own duration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jugger_video_manipulation.overlay_render import (
    Style,
    draw_scoreboard,
    draw_title_card,
    draw_warning,
)
from jugger_video_manipulation.scoreboard import (
    build_states,
    place_segments,
    to_output_time,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from PIL import Image

    from jugger_video_manipulation.cut_json_parser import (
        Display,
        Match,
        Overlay,
        Point,
    )
    from jugger_video_manipulation.overlay_render import CardText, Team

#: A warning with no length of its own stays up this long, in seconds.
DEFAULT_WARNING_SECONDS = 5.0

#: How long the opening card stays up when the file does not say.
DEFAULT_CARD_SECONDS = 4.0


@dataclass(frozen=True)
class CutContent:
    """What a cut file says, as the parser returns it."""

    points: Sequence[Point] = ()
    overlays: Sequence[Overlay] = ()
    match: Match = field(default_factory=dict)
    display: Display = field(default_factory=dict)


@dataclass(frozen=True)
class RenderContext:
    """Everything about how the overlays look, as opposed to what they say."""

    style: Style = field(default_factory=Style)
    background: Image.Image | None = None
    card_text: CardText | None = None
    size: tuple[int, int] = (1920, 1080)


@dataclass(frozen=True)
class Window:
    """One still image and the stretch of render it is painted over."""

    path: Path
    start: float
    end: float

    @property
    def duration(self) -> float:
        """Return how long the image is on screen."""
        return self.end - self.start


@dataclass(frozen=True)
class Intro:
    """The card that goes in front of the match."""

    path: Path
    duration: float


@dataclass
class OverlayPlan:
    """Everything a render needs to draw the match on itself."""

    windows: list[Window] = field(default_factory=list)
    intro: Intro | None = None

    @property
    def offset(self) -> float:
        """Return how far the match is pushed back by the opening card."""
        return self.intro.duration if self.intro else 0.0

    def total_seconds(self) -> float:
        """Return how far into the render the last overlay reaches.

        Used to size the silent track the opening card is concatenated with:
        it only has to outlast the card, but sizing it to the whole render
        costs nothing and cannot come up short.
        """
        end = max((window.end for window in self.windows), default=0.0)
        return end + self.offset

    def files(self) -> list[Path]:
        """Return every image to hand ffmpeg, the card first when there is one."""
        paths = [self.intro.path] if self.intro else []
        return paths + [window.path for window in self.windows]

    def overlay_arguments(self, first_input: int) -> list[tuple[int, float, float]]:
        """Return `(input index, start, end)` for `filter_overlay`.

        Args:
            first_input: the ffmpeg input index of the first overlay image,
                which is the card's index plus one when there is a card.

        Returns:
            One entry per window, already offset by the card's duration.
        """
        base = first_input + (1 if self.intro else 0)
        return [
            (base + index, window.start + self.offset, window.end + self.offset)
            for index, window in enumerate(self.windows)
        ]


def _save(image: Image.Image, path: Path) -> Path:
    """Write an overlay image, making its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _warning_windows(
    overlays: Sequence[Overlay],
    points: Sequence[Point],
    fps: float,
    directory: Path,
    *,
    style: Style,
    position: str,
    size: tuple[int, int],
) -> list[Window]:
    """Place the warnings on the rendered timeline and draw each one.

    A warning is timed in source frames like everything else. One landing in
    dead time is shown at the start of the next kept point — the first instant
    of the render where it could appear at all. One landing past the last kept
    point is dropped: there is no render left to put it in, so it can only be a
    mistake in the cut file.
    """
    segments = place_segments(points, fps)
    windows: list[Window] = []

    for index, overlay in enumerate(overlays):
        if overlay.get("type") != "Warning":
            continue
        start = to_output_time(segments, int(overlay.get("tc", 0)), fps)
        if start is None:
            continue
        length = overlay.get("length")
        seconds = (int(length) / fps) if length else DEFAULT_WARNING_SECONDS
        image = draw_warning(
            str(overlay.get("warning_type", "")),
            str(overlay.get("text", "")),
            style=style,
            position=position,
            size=size,
        )
        windows.append(
            Window(
                path=_save(image, directory / f"warning_{index:03d}.png"),
                start=start,
                end=start + seconds,
            )
        )
    return windows


def build_plan(
    content: CutContent,
    teams: dict[str, Team],
    fps: float,
    directory: Path,
    *,
    context: RenderContext | None = None,
    hold_final: float = 0.0,
) -> OverlayPlan:
    """Draw every overlay a cut file calls for and say when each is shown.

    Args:
        content: what the cut file says.
        teams: the two teams, keyed by the names the match block uses.
        fps: the frame rate the cut file counts in.
        directory: where the images are written.
        context: how the overlays look — fonts, frame size, the background to
            blur behind the opening card, and the words on it.
        hold_final: seconds to hold the closing score past the last point.

    Returns:
        The images, their windows, and the opening card if the file asks for
        one. A file with no `match` block gets no scoreboard, which is how an
        existing cut file keeps rendering exactly as it does today.
    """
    context = context or RenderContext()
    style, size = context.style, context.size
    board = content.display.get("scoreboard") or {}
    position = board.get("position", "bottom")
    plan = OverlayPlan()

    if content.match:
        states = build_states(content.points, content.match, fps, hold_final=hold_final)
        for index, state in enumerate(states):
            image = draw_scoreboard(
                state,
                teams,
                style=style,
                position=position,
                show_logos=board.get("logos", True),
                show_history=board.get("history", True),
                size=size,
            )
            plan.windows.append(
                Window(
                    path=_save(image, directory / f"board_{index:03d}.png"),
                    start=state.start,
                    end=state.end,
                )
            )

    plan.windows.extend(
        _warning_windows(
            content.overlays,
            content.points,
            fps,
            directory,
            style=style,
            position=position,
            size=size,
        )
    )

    card = content.display.get("title_card") or {}
    asks_for_card = any(
        item.get("type") == "TeamIntroduction" for item in content.overlays
    )
    first, second = teams.get("team1"), teams.get("team2")
    if asks_for_card and first is not None and second is not None:
        length = card.get("length")
        seconds = (int(length) / fps) if length else DEFAULT_CARD_SECONDS
        blurred = card.get("background", "blur") == "blur"
        image = draw_title_card(
            first,
            second,
            context.card_text,
            background=context.background if blurred else None,
            style=style,
            size=size,
        )
        plan.intro = Intro(
            path=_save(image, directory / "title_card.png"), duration=seconds
        )

    return plan
