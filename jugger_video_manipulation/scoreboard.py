"""Turning a cut file into what the scoreboard shows, second by second.

Nothing here draws anything. It answers one question: at a given instant of the
*rendered* video, what does the board say? Everything follows from the points
and the match events, so a cut file cannot hold a score that contradicts its
own points.

Two coordinate systems meet here and must not be confused. Points and events
are timed in frames of the concatenated rushes; the board is displayed in
seconds of the finished render, which is shorter because the dead time between
points is cut out — and shorter again when the points are crossfaded into one
another, since a transition makes two points share the same seconds.

That last part is why `crossfade_durations` lives here rather than next to the
ffmpeg graph: the filter that joins the points and the board that is painted
over them must place the render's seconds exactly the same way, or the score
drifts a little further behind the picture with every transition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jugger_video_manipulation.cut_json_parser import (
        MatchEvent,
        Overlay,
        Point,
    )

#: The side a point was scored on names the team standing there at that moment.
SIDES = ("left", "right")

#: How long one point dissolves into the next, in seconds of the render.
CROSSFADE_SECONDS = 1.0

#: How long the render keeps running once the last point is over.
TAIL_SECONDS = 25.0


@dataclass(frozen=True)
class Timing:
    """How the kept points are laid out on the render, beyond the points.

    Attributes:
        crossfade: seconds each point dissolves into the next.
        tail_frames: source frames the last point runs on for once it is
            over — the players shaking hands, the score being read. The video
            keeps playing through them and the board shows the result.
    """

    crossfade: float = 0.0
    tail_frames: int = 0


def crossfade_durations(
    points: Sequence[Point], fps: float, crossfade: float = CROSSFADE_SECONDS
) -> list[float]:
    """Return the transition length between each pair of consecutive points.

    One entry per join, so `n` points give `n - 1` values, and a render with
    one point has none.

    A transition eats into both points it joins, so it is never allowed more
    than half of the shorter one: asked for a second between two points of
    four seconds it gives a second, asked for the same between two flashes of
    half a second it gives a quarter. `xfade` refuses a duration longer than
    its inputs outright, and half is the point where a point would be nothing
    but transition.

    Args:
        points: the cut file's points, in source frames.
        fps: the frame rate those frames are counted in.
        crossfade: the transition length asked for; 0 joins the points cleanly.

    Returns:
        The transition lengths, in seconds, in the order of the joins. All
        zero when no transition is asked for, so the caller always gets one
        value per join and never has to ask whether there are any.
    """
    wanted = max(crossfade, 0.0)
    lengths = [
        (int(point["out"]) - int(point["in"])) / fps
        for point in points
        if int(point["out"]) > int(point["in"])
    ]
    return [
        min(wanted, previous / 2, following / 2)
        for previous, following in pairwise(lengths)
    ]


@dataclass(frozen=True)
class Segment:
    """One kept stretch, placed in both timelines."""

    source_in: int
    source_out: int
    output_start: float
    output_end: float
    scored: str | None

    @property
    def duration(self) -> float:
        """Return the segment length in seconds of the render."""
        return self.output_end - self.output_start


class StartScore(TypedDict):
    """The score when the recording starts, for a match already under way.

    One number per set for each team, oldest first, both lists the same
    length: every entry but the last is a finished set, the last is the set
    being played. `{"team1": [10, 3], "team2": [8, 0]}` is a first set won
    10-8 and a second set starting at 3-0. It is the game's, not the cut's:
    every cut of a match starts from the same score.
    """

    team1: list[int]
    team2: list[int]


def set_scores(value: Any) -> list[int]:
    """Read one team's per-set scores, as a list or as text like `10-3`.

    A dash separates the sets. Anything that is not a whole number counts as
    zero, and negative numbers too.
    """
    if isinstance(value, str):
        pieces: list[Any] = [] if not value.strip() else re.split(r"[-\u2013]", value)
    elif isinstance(value, list):
        pieces = value
    else:
        return []
    scores = []
    for piece in pieces:
        try:
            scores.append(max(int(str(piece).strip()), 0))
        except ValueError:
            scores.append(0)
    return scores


def start_score(team1: Any, team2: Any) -> StartScore | None:
    """Pair the two teams' per-set scores, padding the shorter with zeros.

    Returns:
        The starting score, or None when neither team has any.
    """
    first, second = set_scores(team1), set_scores(team2)
    length = max(len(first), len(second))
    if not length:
        return None
    return {
        "team1": first + [0] * (length - len(first)),
        "team2": second + [0] * (length - len(second)),
    }


@dataclass(frozen=True)
class SetScore:
    """A finished set, as the two teams' point totals."""

    team1: int
    team2: int

    @property
    def winner(self) -> str | None:
        """Return which team won the set, or None on a tie."""
        if self.team1 > self.team2:
            return "team1"
        return "team2" if self.team2 > self.team1 else None


@dataclass(frozen=True)
class BoardState:
    """What the board says over one stretch of the rendered video.

    `left` and `right` name the team standing on each side at that moment, so
    the renderer never has to know about switches: it draws what it is given.
    """

    start: float
    end: float
    left: str
    right: str
    left_score: int
    right_score: int
    finished_sets: tuple[SetScore, ...] = ()
    set_number: int = 1

    @property
    def duration(self) -> float:
        """Return how long this state is on screen."""
        return self.end - self.start


@dataclass
class _Tally:
    """Running state while walking the points."""

    sides: dict[str, str]
    team1: int = 0
    team2: int = 0
    sets: list[SetScore] = field(default_factory=list)

    def award(self, side: str) -> None:
        """Give the point to whichever team is on `side` right now."""
        if self.sides[side] == "team1":
            self.team1 += 1
        else:
            self.team2 += 1

    def swap(self) -> None:
        """Swap which team stands on which side."""
        self.sides = {"left": self.sides["right"], "right": self.sides["left"]}

    def bank(self) -> None:
        """Close the current set and start the next one at zero."""
        self.sets.append(SetScore(self.team1, self.team2))
        self.team1 = self.team2 = 0

    def score_for(self, side: str) -> int:
        """Return the current points of the team on `side`."""
        return self.team1 if self.sides[side] == "team1" else self.team2

    @classmethod
    def starting(cls, start: StartScore | None) -> _Tally:
        """Return the tally before the first point, 0-0 unless told otherwise.

        A recording that starts with the match under way is given the score it
        missed: the sets before the last are finished, the last is the one
        being played. Team 1 still starts on the left.
        """
        tally = cls(sides={"left": "team1", "right": "team2"})
        if not start:
            return tally
        pairs = list(zip(start["team1"], start["team2"], strict=False))
        if not pairs:
            return tally
        tally.sets = [SetScore(team1, team2) for team1, team2 in pairs[:-1]]
        tally.team1, tally.team2 = pairs[-1]
        return tally


def extend_last(points: Sequence[Point], frames: int) -> list[Point]:
    """Return a copy of the points with the last kept one running `frames` on.

    The tail is the same continuous shot as the point it follows: it extends
    that point rather than being a point of its own, or the render would
    dissolve a shot into its own next second and stabilise the two apart.
    """
    extended: list[Point] = [cast("Point", dict(point)) for point in points]
    if frames <= 0:
        return extended
    for point in reversed(extended):
        if int(point["out"]) > int(point["in"]):
            point["out"] = int(point["out"]) + frames
            break
    return extended


def place_segments(
    points: Sequence[Point],
    fps: float,
    crossfade: float = 0.0,
    tail_frames: int = 0,
) -> list[Segment]:
    """Lay the kept points out on the rendered timeline.

    Args:
        points: the cut file's points, in source frames.
        fps: the frame rate those frames are counted in.
        crossfade: how long each point dissolves into the next. A transition
            is shared by the two points it joins, so each one after the first
            starts that much earlier and the whole render is that much
            shorter.
        tail_frames: source frames the last point runs on past its end. Added
            before anything is placed, so the transitions are measured on the
            point as the render plays it.

    Returns:
        One segment per point, carrying both its source range and where it
        lands in the render. Consecutive segments overlap by the length of the
        transition between them.
    """
    points = extend_last(points, tail_frames)
    fades = crossfade_durations(points, fps, crossfade)
    segments: list[Segment] = []
    cursor = 0.0
    for point in points:
        source_in, source_out = int(point["in"]), int(point["out"])
        if source_out <= source_in:
            continue
        if segments:
            cursor -= fades[len(segments) - 1]
        length = (source_out - source_in) / fps
        scored = point.get("point")
        segments.append(
            Segment(
                source_in=source_in,
                source_out=source_out,
                output_start=cursor,
                output_end=cursor + length,
                scored=scored if scored in SIDES else None,
            )
        )
        cursor += length
    return segments


def to_output_time(segments: Sequence[Segment], tc: int, fps: float) -> float | None:
    """Map a source frame onto the rendered timeline.

    A frame inside a kept segment maps to its exact place. A frame in the dead
    time between two segments has no place of its own, so it maps to the start
    of the next kept segment — the first instant of the render where it could
    be shown. A frame past the last kept point is dropped: there is no render
    left to put it in, so it can only be a mistake in the cut file.

    Args:
        segments: the placed segments.
        tc: a frame of the concatenated rushes.
        fps: the frame rate.

    Returns:
        A time in seconds of the render, or None when the frame falls off the
        end.
    """
    for segment in segments:
        if tc < segment.source_in:
            return segment.output_start
        if tc < segment.source_out:
            return segment.output_start + (tc - segment.source_in) / fps
    return None


def score_events(overlays: Sequence[Overlay]) -> list[MatchEvent]:
    """Pull the events that change the score out of the overlay list.

    They are edited alongside the things that are drawn — one list of what
    happens at a timecode — but they draw nothing, so the state machine takes
    only these and ignores the rest.
    """
    events: list[MatchEvent] = [
        {
            "type": "side_switch" if item["type"] == "SideSwitch" else "set_end",
            "tc": int(cast("dict[str, Any]", item)["tc"]),
        }
        for item in overlays
        if item.get("type") in ("SideSwitch", "SetEnd")
    ]
    events.sort(key=lambda event: event["tc"])
    return events


def _apply_event(tally: _Tally, event: MatchEvent) -> None:
    """Play one match event out on the running tally."""
    if event["type"] == "side_switch":
        tally.swap()
    else:
        tally.bank()


def build_states(
    points: Sequence[Point],
    fps: float,
    *,
    overlays: Sequence[Overlay] = (),
    hold_final: float = 0.0,
    crossfade: float = 0.0,
    tail_frames: int = 0,
    start: StartScore | None = None,
) -> list[BoardState]:
    """Walk the match and return what the board shows, stretch by stretch.

    The board updates when a point ends, which is how a scoreboard behaves
    during play: you watch a point with the score it started at, and it changes
    the moment the point is over. A consequence worth knowing: the very last
    point's result is never on screen, because the render stops with it — pass
    `hold_final` to keep the final score up for that many extra seconds.

    Args:
        points: the cut file's points.
        fps: the frame rate the points are counted in.
        overlays: the cut's overlays, from which the side switches and set
            ends are taken. This is where they are edited.
        hold_final: seconds to hold the closing score past the last point.
        crossfade: how long each point dissolves into the next, which is what
            the render does and therefore where the board has to follow.
        tail_frames: source frames the video runs on past the last point. The
            last point's own state stops where the point does, and the board
            shows its result over the tail.
        start: the score the recording starts at, for a match already under
            way. 0-0 when absent.

    Returns:
        Consecutive states covering the whole render, in order.
    """
    segments = place_segments(points, fps, crossfade, tail_frames)
    if not segments:
        return []

    # Team 1 is the team on the left at kick-off, always: the editor orders
    # them that way and flips them with a button rather than recording a
    # separate mapping that could disagree with the names on screen.
    tally = _Tally.starting(start)
    events = score_events(overlays)

    states: list[BoardState] = []
    event_index = 0

    def snapshot(start: float, end: float) -> BoardState:
        return BoardState(
            start=start,
            end=end,
            left=tally.sides["left"],
            right=tally.sides["right"],
            left_score=tally.score_for("left"),
            right_score=tally.score_for("right"),
            finished_sets=tuple(tally.sets),
            set_number=len(tally.sets) + 1,
        )

    tail_seconds = max(tail_frames, 0) / fps
    for segment in segments:
        # Events dated before this point takes place apply first: a switch
        # during the dead time is already in force when play resumes.
        while (
            event_index < len(events) and events[event_index]["tc"] <= segment.source_in
        ):
            _apply_event(tally, events[event_index])
            event_index += 1

        # The last point runs on into the tail: its own state stops where the
        # point did, and the tail shows its result.
        held = tail_seconds if segment is segments[-1] else 0.0
        states.append(snapshot(segment.output_start, segment.output_end - held))

        if segment.scored:
            tally.award(segment.scored)

    if tail_seconds > 0:
        # The board as the match ended. What the cut files after the last
        # point — a set closed, a switch — is not played out over the tail, or
        # a finished match would sit on 0-0 for its last 25 seconds.
        end = segments[-1].output_end
        states.append(snapshot(end - tail_seconds, end))

    # Anything left over closes the match: bank a final set, honour a switch.
    while event_index < len(events):
        _apply_event(tally, events[event_index])
        event_index += 1

    if hold_final > 0:
        last = states[-1].end
        states.append(snapshot(last, last + hold_final))

    return _merge(_meeting(states))


def _meeting(states: Sequence[BoardState]) -> list[BoardState]:
    """Make consecutive states meet instead of overlapping.

    A transition makes two points share their seconds, and each point's state
    covers its own: left as they are, both boards are painted over the same
    second, see-through on see-through, and the two scores show through each
    other. The picture dissolves; the board changes once, halfway through.
    """
    met = list(states)
    for index in range(len(met) - 1):
        current, following = met[index], met[index + 1]
        if following.start < current.end:
            middle = (current.end + following.start) / 2
            met[index] = replace(current, end=middle)
            met[index + 1] = replace(following, start=middle)
    return met


def _merge(states: Sequence[BoardState]) -> list[BoardState]:
    """Join consecutive states that say exactly the same thing.

    This is why the render has fewer states than the editor's list, which
    keeps one per point to show a score beside each row: the same rule, two
    shapes, because they are asked different questions.

    A point that changes nothing on the board — dead time kept in, or a point
    with no `point` value — should not split the overlay into two identical
    images the renderer would then composite twice.
    """
    merged: list[BoardState] = []
    for state in states:
        previous = merged[-1] if merged else None
        same = previous is not None and (
            (
                previous.left,
                previous.right,
                previous.left_score,
                previous.right_score,
                previous.finished_sets,
            )
            == (
                state.left,
                state.right,
                state.left_score,
                state.right_score,
                state.finished_sets,
            )
        )
        if same and previous is not None:
            merged[-1] = BoardState(
                start=previous.start,
                end=state.end,
                left=previous.left,
                right=previous.right,
                left_score=previous.left_score,
                right_score=previous.right_score,
                finished_sets=previous.finished_sets,
                set_number=previous.set_number,
            )
            continue
        merged.append(state)
    return merged
