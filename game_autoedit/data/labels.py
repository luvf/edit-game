"""Cut files turned into a timeline the model can be trained against.

Cut files store frame numbers on the concatenated rushes, which is exactly the
timeline of the archive. Everything downstream works in seconds, so the
conversion happens here, once, with the game's real fps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

# A cut shorter than this is a leftover, not a point.
MIN_SEGMENT_SECONDS = 1.0

# Two kept segments closer than this were one action split by the editor.
MERGE_GAP_SECONDS = 0.2


@dataclass(frozen=True)
class Segment:
    """One kept stretch of the game, in seconds on the archive timeline."""

    start: float
    end: float
    point: str = "nopoint"

    @property
    def duration(self) -> float:
        """Return the segment length in seconds."""
        return self.end - self.start


@dataclass
class GameLabels:
    """The full label timeline of one game."""

    game_id: int
    fps: float
    segments: list[Segment]
    warnings: list[str]

    @property
    def ins(self) -> list[float]:
        """Return the start boundaries, in seconds."""
        return [segment.start for segment in self.segments]

    @property
    def outs(self) -> list[float]:
        """Return the end boundaries, in seconds."""
        return [segment.end for segment in self.segments]

    @property
    def kept_seconds(self) -> float:
        """Return the total kept duration."""
        return sum(segment.duration for segment in self.segments)

    def gaps(self) -> list[float]:
        """Return the dead time between consecutive kept segments, in seconds."""
        return [
            nxt.start - cur.end
            for cur, nxt in zip(self.segments, self.segments[1:], strict=False)
        ]


def _raw_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the point list of a cut payload, tolerating an empty file."""
    points = payload.get("points")
    return points if isinstance(points, list) else []


def has_points(cut_json_path: Path) -> bool:
    """Tell whether a cut file holds at least one usable point.

    Cheap enough to run over the whole catalog: the files are a few kilobytes
    and this needs neither the fps nor the media duration.
    """
    try:
        with cut_json_path.open() as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return any(
        isinstance(point, dict) and "in" in point and "out" in point
        for point in _raw_points(payload)
    )


def load_labels(
    cut_json_path: Path,
    *,
    game_id: int,
    fps: float,
    duration: float | None = None,
) -> GameLabels:
    """Read a cut file and convert it to a checked timeline in seconds.

    Args:
        cut_json_path: the cut file to read.
        game_id: the game the cut belongs to, for reporting.
        fps: the archive frame rate the cut frames refer to.
        duration: the audio duration in seconds, when known, to catch cuts that
            run past the end of the media.

    Returns:
        The segments, plus every anomaly found while reading them.
    """
    warnings: list[str] = []
    with cut_json_path.open() as handle:
        payload = json.load(handle)

    segments: list[Segment] = []
    for raw in _raw_points(payload):
        try:
            start = float(raw["in"]) / fps
            end = float(raw["out"]) / fps
        except (KeyError, TypeError, ValueError):
            warnings.append(f"point illisible ignoré: {raw!r}")
            continue

        if end <= start:
            warnings.append(f"segment vide ou inversé ignoré: {start:.2f}-{end:.2f}s")
            continue
        segments.append(Segment(start, end, raw.get("point") or "nopoint"))

    segments.sort(key=lambda segment: segment.start)
    segments = _drop_overlaps(segments, warnings)
    segments = _merge_close(segments, warnings)
    segments = _drop_short(segments, warnings)

    if duration is not None:
        segments = _clip_to_duration(segments, duration, warnings)

    return GameLabels(game_id=game_id, fps=fps, segments=segments, warnings=warnings)


def _drop_overlaps(segments: list[Segment], warnings: list[str]) -> list[Segment]:
    """Drop segments that start before the previous one ended."""
    kept: list[Segment] = []
    for segment in segments:
        if kept and segment.start < kept[-1].end:
            warnings.append(
                f"chevauchement ignoré: {segment.start:.2f}-{segment.end:.2f}s"
            )
            continue
        kept.append(segment)
    return kept


def _merge_close(segments: list[Segment], warnings: list[str]) -> list[Segment]:
    """Merge segments separated by less than `MERGE_GAP_SECONDS`."""
    merged: list[Segment] = []
    for segment in segments:
        if merged and segment.start - merged[-1].end < MERGE_GAP_SECONDS:
            previous = merged.pop()
            warnings.append(
                f"segments fusionnés autour de {previous.end:.2f}s "
                f"(écart {segment.start - previous.end:.3f}s)"
            )
            merged.append(Segment(previous.start, segment.end, previous.point))
            continue
        merged.append(segment)
    return merged


def _drop_short(segments: list[Segment], warnings: list[str]) -> list[Segment]:
    """Drop segments too short to be a real point."""
    kept = []
    for segment in segments:
        if segment.duration < MIN_SEGMENT_SECONDS:
            warnings.append(
                f"segment trop court ignoré: {segment.duration:.2f}s "
                f"à {segment.start:.2f}s"
            )
            continue
        kept.append(segment)
    return kept


def _clip_to_duration(
    segments: list[Segment], duration: float, warnings: list[str]
) -> list[Segment]:
    """Clip or drop segments that run past the end of the audio."""
    kept: list[Segment] = []
    for segment in segments:
        if segment.start >= duration:
            warnings.append(
                f"segment hors média ignoré: {segment.start:.2f}s > {duration:.2f}s"
            )
            continue
        if segment.end > duration:
            warnings.append(
                f"segment tronqué à la fin du média: {segment.end:.2f}s -> {duration:.2f}s"
            )
            kept.append(Segment(segment.start, duration, segment.point))
            continue
        kept.append(segment)
    return kept
