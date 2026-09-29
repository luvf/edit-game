"""Detect jugger point windows from video activity and export JSON."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ffmpeg
import numpy as np


@dataclass(slots=True)
class VideoMeta:
    """Minimal video metadata needed for activity analysis."""

    width: int
    height: int
    duration_s: float
    fps: float


@dataclass(slots=True)
class Segment:
    """Half-open active segment [start_idx, end_idx) over sampled frames."""

    start_idx: int
    end_idx: int


def _seconds_to_timecode(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm."""
    s = max(0.0, float(seconds))
    hours = int(s // 3600)
    s -= hours * 3600
    minutes = int(s // 60)
    s -= minutes * 60
    whole = int(s)
    millis = int(round((s - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    if whole == 60:
        minutes += 1
        whole = 0
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{millis:03d}"


def _probe_video(video_path: Path) -> VideoMeta:
    """Read width, height, duration and fps with ffprobe."""
    try:
        info = ffmpeg.probe(str(video_path))
    except ffmpeg.Error as exc:
        stderr = (
            exc.stderr.decode("utf-8", errors="ignore")
            if hasattr(exc, "stderr") and isinstance(exc.stderr, (bytes, bytearray))
            else str(exc)
        )
        raise RuntimeError(f"ffprobe failed: {stderr}") from exc

    streams = info.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise ValueError(f"No video stream found in {video_path}")

    width = int(vstream.get("width") or 0)
    height = int(vstream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid video dimensions in {video_path}")

    rate = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "0/0"
    fps = 25.0
    if rate != "0/0" and "/" in rate:
        try:
            num, den = rate.split("/")
            den_i = int(den)
            if den_i != 0:
                fps = int(num) / den_i
        except ValueError:
            fps = 25.0

    duration_raw = vstream.get("duration") or info.get("format", {}).get("duration")
    duration_s = float(duration_raw) if duration_raw is not None else 0.0
    if duration_s <= 0:
        raise ValueError(f"Invalid duration for {video_path}")

    return VideoMeta(width=width, height=height, duration_s=duration_s, fps=fps)


def _fill_short_inactive_gaps(active: np.ndarray, max_gap: int) -> np.ndarray:
    """Fill inactive gaps between active regions when the gap is short."""
    if max_gap <= 0 or active.size == 0:
        return active

    out = active.copy()
    idx = 0
    n = int(out.size)
    while idx < n:
        if out[idx]:
            idx += 1
            continue
        start = idx
        while idx < n and not out[idx]:
            idx += 1
        end = idx
        left_active = start > 0 and out[start - 1]
        right_active = end < n and out[end]
        if left_active and right_active and (end - start) <= max_gap:
            out[start:end] = True
    return out


def _remove_short_active_segments(active: np.ndarray, min_len: int) -> np.ndarray:
    """Drop active segments smaller than min_len samples."""
    if min_len <= 1 or active.size == 0:
        return active

    out = active.copy()
    idx = 0
    n = int(out.size)
    while idx < n:
        if not out[idx]:
            idx += 1
            continue
        start = idx
        while idx < n and out[idx]:
            idx += 1
        end = idx
        if (end - start) < min_len:
            out[start:end] = False
    return out


def _to_segments(active: np.ndarray) -> list[Segment]:
    """Convert active mask to half-open segments."""
    segments: list[Segment] = []
    idx = 0
    n = int(active.size)
    while idx < n:
        if not active[idx]:
            idx += 1
            continue
        start = idx
        while idx < n and active[idx]:
            idx += 1
        segments.append(Segment(start_idx=start, end_idx=idx))
    return segments


def _activity_scores(
    video_path: Path,
    *,
    sample_fps: float,
    analysis_width: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute raw per-sample activity scores and timestamps."""
    meta = _probe_video(video_path)
    if sample_fps <= 0:
        raise ValueError("sample_fps must be > 0")
    if analysis_width <= 32:
        raise ValueError("analysis_width must be > 32")

    target_w = int(analysis_width)
    target_h = max(2, int(round(meta.height * (target_w / meta.width))))
    frame_size = target_w * target_h

    process = (
        ffmpeg.input(str(video_path))
        .filter("fps", fps=sample_fps)
        .filter("scale", target_w, target_h)
        .output("pipe:", format="rawvideo", pix_fmt="gray")
        .run_async(pipe_stdout=True, pipe_stderr=True)
    )

    scores: list[float] = []
    times: list[float] = []
    previous: np.ndarray | None = None
    sample_idx = 0
    try:
        while True:
            chunk = process.stdout.read(frame_size)
            if not chunk:
                break
            if len(chunk) != frame_size:
                break
            current = np.frombuffer(chunk, dtype=np.uint8).reshape((target_h, target_w))
            if previous is not None:
                temporal = float(
                    np.mean(np.abs(current.astype(np.int16) - previous.astype(np.int16)))
                ) / 255.0
                # Lightweight spatial texture term to avoid classifying static dark scenes as active.
                spatial = float(np.mean(np.abs(np.diff(current, axis=1)))) / 255.0
                score = 0.75 * temporal + 0.25 * spatial
                scores.append(score)
                times.append(sample_idx / sample_fps)
            previous = current
            sample_idx += 1
    finally:
        stderr = process.stderr.read().decode("utf-8", errors="ignore")
        retcode = process.wait()
        if retcode != 0:
            raise RuntimeError(f"ffmpeg frame sampling failed: {stderr}")

    return np.asarray(scores, dtype=np.float32), np.asarray(times, dtype=np.float32)


def detect_activity_points(
    video_path: str | Path,
    *,
    sample_fps: float = 2.0,
    analysis_width: int = 224,
    smoothing_seconds: float = 2.0,
    activity_quantile: float = 0.65,
    min_point_seconds: float = 8.0,
    max_pause_seconds: float = 3.0,
) -> dict[str, Any]:
    """Detect likely jugger points based on video activity.

    This is a heuristic baseline:
    - samples grayscale frames at low FPS
    - computes movement + texture activity
    - smoothes scores
    - segments active windows into candidate points
    """
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(source)
    if not 0.05 <= activity_quantile <= 0.95:
        raise ValueError("activity_quantile must be between 0.05 and 0.95")

    raw_scores, times = _activity_scores(
        source, sample_fps=sample_fps, analysis_width=analysis_width
    )
    if raw_scores.size == 0:
        return {
            "source_video": str(source),
            "algorithm": "activity-v1",
            "points": [],
            "summary": {
                "message": "No scores computed from video",
                "sample_fps": sample_fps,
                "frames_analyzed": 0,
            },
        }

    smooth_window = max(1, int(round(smoothing_seconds * sample_fps)))
    if smooth_window > 1:
        kernel = np.ones(smooth_window, dtype=np.float32) / float(smooth_window)
        smooth_scores = np.convolve(raw_scores, kernel, mode="same")
    else:
        smooth_scores = raw_scores

    threshold = float(np.quantile(smooth_scores, activity_quantile))
    active = smooth_scores >= threshold
    active = _fill_short_inactive_gaps(
        active, max_gap=max(0, int(round(max_pause_seconds * sample_fps)))
    )
    active = _remove_short_active_segments(
        active, min_len=max(1, int(round(min_point_seconds * sample_fps)))
    )
    segments = _to_segments(active)

    points: list[dict[str, Any]] = []
    for i, segment in enumerate(segments, start=1):
        start_s = float(times[segment.start_idx])
        end_ref_idx = min(segment.end_idx - 1, times.size - 1)
        end_s = float(times[end_ref_idx] + (1.0 / sample_fps))
        points.append(
            {
                "point_id": i,
                "start_seconds": round(start_s, 3),
                "end_seconds": round(end_s, 3),
                "start_timecode": _seconds_to_timecode(start_s),
                "end_timecode": _seconds_to_timecode(end_s),
                "duration_seconds": round(max(0.0, end_s - start_s), 3),
            }
        )

    summary = {
        "sample_fps": sample_fps,
        "frames_analyzed": int(raw_scores.size),
        "threshold": round(threshold, 6),
        "raw_score_mean": round(float(np.mean(raw_scores)), 6),
        "raw_score_std": round(float(np.std(raw_scores)), 6),
    }

    return {
        "source_video": str(source),
        "algorithm": "activity-v1",
        "parameters": {
            "analysis_width": analysis_width,
            "smoothing_seconds": smoothing_seconds,
            "activity_quantile": activity_quantile,
            "min_point_seconds": min_point_seconds,
            "max_pause_seconds": max_pause_seconds,
        },
        "summary": summary,
        "points": points,
    }


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Detect likely jugger points from video activity and export JSON."
    )
    parser.add_argument("--video", required=True, help="Path to input video file.")
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output JSON file (created/overwritten).",
    )
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--analysis-width", type=int, default=224)
    parser.add_argument("--smoothing-seconds", type=float, default=2.0)
    parser.add_argument("--activity-quantile", type=float, default=0.65)
    parser.add_argument("--min-point-seconds", type=float, default=8.0)
    parser.add_argument("--max-pause-seconds", type=float, default=3.0)
    args = parser.parse_args()

    result = detect_activity_points(
        args.video,
        sample_fps=args.sample_fps,
        analysis_width=args.analysis_width,
        smoothing_seconds=args.smoothing_seconds,
        activity_quantile=args.activity_quantile,
        min_point_seconds=args.min_point_seconds,
        max_pause_seconds=args.max_pause_seconds,
    )
    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
