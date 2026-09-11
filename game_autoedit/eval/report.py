"""The structured commentary shipped alongside a predicted cut.

A cut file alone gives a reviewer no way to know where to look. This builds the
part that does: the shape of what was produced, and the places where the model
was unsure or where the result does not look like a normal game.
"""

from __future__ import annotations

import itertools
import statistics
from typing import TYPE_CHECKING, Any

from game_autoedit.eval.decode import DEFAULT_THRESHOLD

if TYPE_CHECKING:
    from game_autoedit.data.labels import Segment
    from game_autoedit.eval.decode import Decoded, DecodeSpec

# A duration this many times off the game's own median is worth a look.
OUTLIER_RATIO = 2.5

# A boundary this close to its trigger level could go either way.
MARGIN = 0.1

# Below this many segments a median says nothing, so nothing is flagged.
MIN_FOR_MEDIAN = 3


def _distribution(values: list[float]) -> dict[str, float]:
    """Return a small summary of a list of durations, in seconds."""
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median": round(statistics.median(ordered), 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "total": round(sum(ordered), 2),
    }


def _long_segments(segments: list[Segment]) -> list[dict[str, Any]]:
    """Flag segments far longer than this game's own median."""
    durations = [segment.duration for segment in segments]
    if len(durations) < MIN_FOR_MEDIAN:
        return []
    median = statistics.median(durations)
    if median <= 0:
        return []
    return [
        {
            "at": round(segment.start, 2),
            "kind": "segment_long",
            "detail": (
                f"{segment.duration:.0f}s contre {median:.0f}s en médiane : "
                f"un out a peut-être été manqué"
            ),
        }
        for segment in segments
        if segment.duration > median * OUTLIER_RATIO
    ]


def _long_gaps(segments: list[Segment], gaps: list[float]) -> list[dict[str, Any]]:
    """Flag dead time far longer than this game's own median."""
    if len(gaps) < MIN_FOR_MEDIAN:
        return []
    median = statistics.median(gaps)
    if median <= 0:
        return []
    return [
        {
            "at": round(segments[index].end, 2),
            "kind": "pause_longue",
            "detail": (
                f"{gap:.0f}s sans point contre {median:.0f}s en médiane : "
                f"discussion d'arbitres, ou un point non détecté"
            ),
        }
        for index, gap in enumerate(gaps)
        if gap > median * OUTLIER_RATIO
    ]


def _uncertain(decoded: Decoded, spec: DecodeSpec) -> list[dict[str, Any]]:
    """Flag the boundaries that sat just above their trigger level."""
    return [
        {
            "at": round(peak.time, 2),
            "kind": f"{peak.channel}_incertain",
            "detail": (
                f"score {peak.score:.2f} pour un seuil de "
                f"{spec.threshold.get(peak.channel, DEFAULT_THRESHOLD):.2f}"
            ),
        }
        for peak in decoded.peaks
        if peak.score < spec.threshold.get(peak.channel, DEFAULT_THRESHOLD) + MARGIN
    ]


def build_comment(
    decoded: Decoded,
    *,
    duration: float,
    fps: float,
    decode_spec: DecodeSpec,
    model_info: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the commentary block of a predicted cut file.

    Args:
        decoded: what the decoder produced, including its rejections.
        duration: the game duration in seconds.
        fps: the frame rate the cut frames are expressed in.
        decode_spec: the thresholds used, so a result can be reproduced.
        model_info: which run produced this.

    Returns:
        A JSON-serialisable block: what was produced, and what to check.
    """
    segments = decoded.segments
    gaps = [nxt.start - cur.end for cur, nxt in itertools.pairwise(segments)]
    kept = sum(segment.duration for segment in segments)

    review = (
        _long_segments(segments)
        + _long_gaps(segments, gaps)
        + _uncertain(decoded, decode_spec)
    )
    review.sort(key=lambda item: item["at"])

    return {
        "generated_by": "game_autoedit",
        "model": model_info,
        "fps": round(fps, 6),
        "decode": {
            "threshold": dict(decode_spec.threshold),
            "min_peak_distance": decode_spec.min_peak_distance,
            "min_duration": decode_spec.min_duration,
            "max_duration": decode_spec.max_duration,
            "inside_veto": decode_spec.inside_veto,
        },
        "stats": {
            "duration": round(duration, 2),
            "kept": round(kept, 2),
            "kept_ratio": round(kept / duration, 4) if duration else 0.0,
            "segments": _distribution([segment.duration for segment in segments]),
            "gaps": _distribution(gaps),
        },
        "review": review,
        "rejected": [rejection.as_dict() for rejection in decoded.dropped],
    }
