"""Turning a cut file into the images and windows a render needs.

This is the join between the three pieces that already exist: the parser reads
the file, `scoreboard` says what the board shows and when, `overlay_render`
draws it. Here each state becomes a PNG on disk and a window in seconds of the
finished render, which is exactly what `filter_overlay` consumes.

The opening card is handled apart, because it is not an overlay: it goes in
front of the match rather than over it, so it lengthens the render and pushes
everything else back — by its own duration, less the transition it dissolves
into the match with, which the match plays under.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jugger_video_manipulation.overlay_render import (
    Style,
    draw_scoreboard,
    draw_title_card,
    draw_warning,
    scoreboard_layout,
)
from jugger_video_manipulation.scoreboard import (
    Timing,
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
        Overlay,
        Point,
        TitleCardDisplay,
    )
    from jugger_video_manipulation.overlay_render import CardText, Team
    from jugger_video_manipulation.scoreboard import Segment, StartScore

#: A warning with no length of its own stays up this long, in seconds.
DEFAULT_WARNING_SECONDS = 5.0

#: How long the opening card stays up when the file does not say.
DEFAULT_CARD_SECONDS = 4.0

#: The least footage before the first point worth playing behind the card. A
#: match filmed from its very first second has none: its card stays still.
MIN_PRE_ROLL_SECONDS = 1.0


@dataclass(frozen=True)
class CutContent:
    """What a cut file says, as the parser returns it, and where its score starts.

    `start_score` is not in the file: it is the game's, the same for every cut
    of the match, and handed in by whoever knows the game.
    """

    points: Sequence[Point] = ()
    overlays: Sequence[Overlay] = ()
    display: Display = field(default_factory=dict)
    start_score: StartScore | None = None


@dataclass(frozen=True)
class RenderContext:
    """Everything about how the overlays look, as opposed to what they say."""

    style: Style = field(default_factory=Style)
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
    """The card that goes in front of the match.

    Attributes:
        path: the card image.
        duration: how long the card is up, its dissolve included.
        fade: how long the card dissolves into the match, taken out of
            `duration`.
        source_start: where, in frames of the concatenated rushes, the
            footage behind the card starts. The card then plays the seconds
            before the first point, blurred and darkened with its sound low,
            and dissolves as that point begins. None for a still card.
    """

    path: Path
    duration: float
    fade: float = 0.0
    source_start: int | None = None


@dataclass
class OverlayPlan:
    """Everything a render needs to draw the match on itself."""

    windows: list[Window] = field(default_factory=list)
    intro: Intro | None = None

    @property
    def offset(self) -> float:
        """Return how far the match is pushed back by the opening card.

        The transition does not count: the match is already playing under the
        card while it disappears, so it starts when the dissolve starts.
        """
        if self.intro is None:
            return 0.0
        return self.intro.duration - self.intro.fade

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


def _wants_scoreboard(content: CutContent) -> bool:
    """Tell whether the file says enough for a board to mean anything.

    Either a point says who scored, or the game gives the score the recording
    starts at.
    """
    if any(point.get("point") in ("left", "right") for point in content.points):
        return True
    return bool(content.start_score)


def _save(image: Image.Image, path: Path) -> Path:
    """Write an overlay image, making its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _warning_windows(
    content: CutContent,
    segments: Sequence[Segment],
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

    Two warnings whose windows overlap are moved apart on the picture rather
    than in time: each takes the lowest row free when it comes up, so both stay
    on screen for exactly as long as the file says and neither hides the other.
    """
    timed = []
    for index, overlay in enumerate(content.overlays):
        if overlay.get("type") != "Warning":
            continue
        start = to_output_time(segments, int(overlay.get("tc", 0)), fps)
        if start is None:
            continue
        length = overlay.get("length")
        seconds = (int(length) / fps) if length else DEFAULT_WARNING_SECONDS
        timed.append((index, overlay, start, start + seconds))

    windows: list[Window] = []
    #: When each row frees up, in seconds of the render.
    free_from: list[float] = []
    for index, overlay, start, end in sorted(timed, key=lambda item: item[2]):
        row = next(
            (row for row, until in enumerate(free_from) if start >= until),
            len(free_from),
        )
        if row == len(free_from):
            free_from.append(end)
        else:
            free_from[row] = end
        image = draw_warning(
            str(overlay.get("warning_type", "")),
            str(overlay.get("text", "")),
            style=style,
            position=position,
            row=row,
            size=size,
        )
        windows.append(
            Window(
                path=_save(image, directory / f"warning_{index:03d}.png"),
                start=start,
                end=end,
            )
        )
    return windows


def _pre_roll_start(
    content: CutContent,
    fps: float,
    wanted: float,
    fade: float,
    card: TitleCardDisplay,
) -> int | None:
    """Return where the footage behind the card starts, or None for a still card.

    The seconds just before the first kept point, as many as the card wants
    and the rushes hold. The dissolve then starts on the point's first frame.

    Args:
        content: what the cut file says.
        fps: the frame rate the points are counted in.
        wanted: how much footage the card would play before the point.
        fade: how long the dissolve lasts; the footage must at least cover it.
        card: the file's title card options; `flat` asks for a still card.
    """
    if card.get("background", "blur") != "blur":
        return None
    kept = [point for point in content.points if int(point["out"]) > int(point["in"])]
    if not kept:
        return None
    first_in = int(kept[0]["in"])
    pre_roll = min(wanted, first_in / fps)
    if pre_roll < max(MIN_PRE_ROLL_SECONDS, fade):
        return None
    return first_in - round(pre_roll * fps)


def build_plan(
    content: CutContent,
    teams: dict[str, Team],
    fps: float,
    directory: Path,
    *,
    context: RenderContext | None = None,
    hold_final: float = 0.0,
    timing: Timing | None = None,
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
        timing: the transitions and the tail the render plays. The windows
            follow the picture, so they are placed on the same timeline; the
            opening card dissolves for as long as a transition, and the final
            score stays up over the tail.

    Returns:
        The images, their windows, and the opening card if the file asks for
        one.

        A scoreboard appears as soon as the file says who scored: any point
        marked `left` or `right`. A file that never says gets none, which is
        how the cuts that exist today keep rendering exactly as they do today.
    """
    context = context or RenderContext()
    timing = timing or Timing()
    segments = place_segments(content.points, fps, timing.crossfade, timing.tail_frames)
    style, size = context.style, context.size
    board = content.display.get("scoreboard") or {}
    position = board.get("position", "bottom")
    plan = OverlayPlan()

    if _wants_scoreboard(content):
        states = build_states(
            content.points,
            fps,
            overlays=content.overlays,
            hold_final=hold_final,
            crossfade=timing.crossfade,
            tail_frames=timing.tail_frames,
            start=content.start_score,
        )
        # One layout for the whole match: every board comes out the same size.
        layout = scoreboard_layout(
            states,
            teams,
            style=style,
            show_logos=board.get("logos", True),
            show_history=board.get("history", True),
            size=size,
        )
        for index, state in enumerate(states):
            image = draw_scoreboard(
                state,
                teams,
                style=style,
                position=position,
                show_logos=board.get("logos", True),
                show_history=board.get("history", True),
                size=size,
                layout=layout,
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
            content,
            segments,
            fps,
            directory,
            style=style,
            position=position,
            size=size,
        )
    )

    card = content.display.get("title_card") or {}
    # The card is on by default: only an explicit "no" from the editor drops it.
    asks_for_card = content.display.get("intro", True) is not False
    first, second = teams.get("team1"), teams.get("team2")
    if asks_for_card and first is not None and second is not None:
        length = card.get("length")
        seconds = (int(length) / fps) if length else DEFAULT_CARD_SECONDS
        # The card never dissolves away more than half of itself: a four
        # second card gives a second to the transition, a one second card
        # half of one.
        fade = min(timing.crossfade, seconds / 2)
        start = _pre_roll_start(content, fps, seconds - fade, fade, card)
        if start is not None:
            # The footage behind the card runs up to the first point: the
            # card lasts as long as there is footage, then dissolves.
            seconds = (int(segments[0].source_in) - start) / fps + fade
        image = draw_title_card(
            first,
            second,
            context.card_text,
            style=style,
            size=size,
            transparent=start is not None,
        )
        plan.intro = Intro(
            path=_save(image, directory / "title_card.png"),
            duration=seconds,
            fade=fade,
            source_start=start,
        )

    return plan
