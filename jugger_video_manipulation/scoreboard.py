"""Turning a cut file into what the scoreboard shows, second by second.

Nothing here draws anything. It answers one question: at a given instant of the
*rendered* video, what does the board say? Everything follows from the points
and the match events, so a cut file cannot hold a score that contradicts its
own points.

Two coordinate systems meet here and must not be confused. Points and events
are timed in frames of the concatenated rushes; the board is displayed in
seconds of the finished render, which is shorter because the dead time between
points is cut out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jugger_video_manipulation.cut_json_parser import Match, Point

#: The side a point was scored on names the team standing there at that moment.
SIDES = ("left", "right")


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


def place_segments(points: Sequence[Point], fps: float) -> list[Segment]:
    """Lay the kept points out on the rendered timeline.

    Args:
        points: the cut file's points, in source frames.
        fps: the frame rate those frames are counted in.

    Returns:
        One segment per point, carrying both its source range and where it
        lands in the render.
    """
    segments: list[Segment] = []
    cursor = 0.0
    for point in points:
        source_in, source_out = int(point["in"]), int(point["out"])
        if source_out <= source_in:
            continue
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


def build_states(
    points: Sequence[Point],
    match: Match,
    fps: float,
    *,
    hold_final: float = 0.0,
) -> list[BoardState]:
    """Walk the match and return what the board shows, stretch by stretch.

    The board updates when a point ends, which is how a scoreboard behaves
    during play: you watch a point with the score it started at, and it changes
    the moment the point is over. A consequence worth knowing: the very last
    point's result is never on screen, because the render stops with it — pass
    `hold_final` to keep the final score up for that many extra seconds.

    Args:
        points: the cut file's points.
        match: the match block, giving the starting sides and the events.
        fps: the frame rate the points are counted in.
        hold_final: seconds to hold the closing score past the last point.

    Returns:
        Consecutive states covering the whole render, in order.
    """
    segments = place_segments(points, fps)
    if not segments:
        return []

    start_sides = match.get("start_sides") or {"left": "team1", "right": "team2"}
    tally = _Tally(sides={"left": start_sides["left"], "right": start_sides["right"]})
    events = list(match.get("events") or [])

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

    for segment in segments:
        # Events dated before this point takes place apply first: a switch
        # during the dead time is already in force when play resumes.
        while (
            event_index < len(events) and events[event_index]["tc"] <= segment.source_in
        ):
            event = events[event_index]
            if event["type"] == "side_switch":
                tally.swap()
            else:
                tally.bank()
            event_index += 1

        states.append(snapshot(segment.output_start, segment.output_end))

        if segment.scored:
            tally.award(segment.scored)

    # Anything left over closes the match: bank a final set, honour a switch.
    while event_index < len(events):
        event = events[event_index]
        if event["type"] == "side_switch":
            tally.swap()
        else:
            tally.bank()
        event_index += 1

    if hold_final > 0:
        last = states[-1].end
        states.append(snapshot(last, last + hold_final))

    return _merge(states)


def _merge(states: Sequence[BoardState]) -> list[BoardState]:
    """Join consecutive states that say exactly the same thing.

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
