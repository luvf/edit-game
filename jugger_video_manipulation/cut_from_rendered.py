"""Cut detection from a rendered video."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

import ffmpeg  # type: ignore[import-untyped]
import numpy as np
import torchaudio
from scipy.signal import correlate, correlation_lags


def _ensure_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)


def _pick_video_fps(video_path: Path) -> float:
    metadata = ffmpeg.probe(str(video_path))
    streams = metadata.get("streams", [])
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        rate = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
        if not rate:
            continue
        if isinstance(rate, str) and "/" in rate:
            num, den = rate.split("/", 1)
            try:
                return float(num) / float(den)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
        try:
            return float(rate)
        except (TypeError, ValueError):
            continue
    return 25.0


def _get_chapters_seconds(video_path: Path) -> list[tuple[float, float]]:
    metadata = ffmpeg.probe(str(video_path), show_chapters=None)
    chapters: list[tuple[float, float]] = []
    for chapter in metadata.get("chapters", []):
        try:
            start = float(chapter["start_time"])
            end = float(chapter["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            chapters.append((start, end))
    return chapters


def _build_concat_file(
    source_dir: Path,
    source_files: list[str],
    tmp_dir: Path,
) -> Path:
    _ensure_dir(tmp_dir)
    concat_path = tmp_dir / f"concat_sources_{uuid.uuid4().hex}.txt"
    rush_dir = source_dir / "rushs"
    with concat_path.open("w", encoding="utf-8") as handle:
        for filename in source_files:
            candidate = rush_dir / filename
            if not candidate.exists():
                candidate = source_dir / filename
            if not candidate.exists():
                raise FileNotFoundError(f"Missing source file: {filename}")
            handle.write(f"file '{candidate.absolute()}'\n")
    return concat_path


def _extract_audio(
    input_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    is_concat: bool = False,
) -> None:
    args = ["ffmpeg", "-y"]
    if is_concat:
        args.extend(["-f", "concat", "-safe", "0", "-i", str(input_path)])
    else:
        args.extend(["-i", str(input_path)])
    args.extend(
        [
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(output_path),
        ]
    )
    subprocess.run(args, check=True)


def _rescale(audio: Any) -> Any:
    audio = audio - audio.mean()
    max_abs = audio.abs().max()
    max_abs_value = max_abs.item() if hasattr(max_abs, "item") else float(max_abs)
    if max_abs_value > 0:
        audio = audio / max_abs_value
    return audio


def _align_scipy(
    source: Any,
    target: Any,
    start_source: int,
    end_source: int,
    start_target: int,
    end_target: int,
) -> tuple[int, float]:
    correlation = correlate(
        source[start_source:end_source], target[start_target:end_target]
    )
    lags = correlation_lags(end_source - start_source, end_target - start_target)
    ret = int(lags[np.argmax(correlation)])
    return ret, float(np.max(correlation))


def _reload_video_from_sources(
    source_dir: Path,
    source_files: list[str],
    target_path: Path,
    *,
    build_tmp: bool,
    sample_rate: int,
    tmp_dir: Path,
) -> tuple[Any, int, Any, int, float]:
    _ensure_dir(tmp_dir)
    concat_path = _build_concat_file(source_dir, source_files, tmp_dir)
    source_audio_path = tmp_dir / f"source_audio_{uuid.uuid4().hex}.wav"
    target_audio_path = tmp_dir / f"target_audio_{uuid.uuid4().hex}.wav"

    _extract_audio(
        concat_path, source_audio_path, sample_rate=sample_rate, is_concat=True
    )
    _extract_audio(target_path, target_audio_path, sample_rate=sample_rate)

    source_audio, s_sample = torchaudio.load(str(source_audio_path))
    target_audio, t_sample = torchaudio.load(str(target_audio_path))
    fps = _pick_video_fps(target_path)

    if not build_tmp:
        concat_path.unlink(missing_ok=True)
        source_audio_path.unlink(missing_ok=True)
        target_audio_path.unlink(missing_ok=True)

    return source_audio, s_sample, target_audio, t_sample, fps


def build_cut_points_from_rendered_audio(
    source_dir: str | Path,
    source_files: list[str],
    target_path: str | Path,
    *,
    sample_rate: int = 16000,
    threshold: float = 90.0,
    buffer_seconds: float = 2.0,
    search_window_factor: int = 300,
    refine_window_factor: int = 10,
    fallback_window_factor: int = 400,
    segment_gap_factor: float = 2.0,
    chapter_search_factor: float = 2.0,
    chapter_min_gap_seconds: float = 30.0,
    chapter_start_offset_seconds: float = 1.0,
    use_chapters: bool = True,
    tmp_dir: str | Path = "core/tmp",
) -> list[dict[str, int | str]]:
    """Build cut points by aligning a rendered video to its source rushes.

    The function extracts mono audio from the concatenated source files and the
    rendered video, then slides a window across the rendered audio. Each window
    is aligned to the source audio via cross-correlation, yielding a list of
    matched offsets. These offsets are grouped into continuous segments that
    become cut points expressed in frames.

    Tuning parameters:
        sample_rate: Audio resampling rate used for alignment.
        threshold: Minimum correlation score to accept a match.
        buffer_seconds: Duration (seconds) of the sliding window.
        search_window_factor: Multiplier for the initial search range.
        refine_window_factor: Multiplier for the next-step range after a match.
        fallback_window_factor: Multiplier for the next-step range after a miss.
        segment_gap_factor: Minimum gap (in buffer sizes) to start a new segment.
        chapter_search_factor: Multiplier for chapter-duration search range.
        chapter_min_gap_seconds: Minimum gap in source seconds between chapters.
        chapter_start_offset_seconds: Seconds to skip at chapter start for matching.
        use_chapters: When True, align each chapter using its full duration.
        tmp_dir: Directory for temp files.
    """
    source_audio, _, target_audio, _, fps = _reload_video_from_sources(
        Path(source_dir),
        source_files,
        Path(target_path),
        build_tmp=True,
        sample_rate=sample_rate,
        tmp_dir=Path(tmp_dir),
    )

    source_audio = _rescale(source_audio)
    target_audio = _rescale(target_audio)

    target_len = target_audio.shape[1]
    source_len = source_audio.shape[1]

    buffer = max(1, int(buffer_seconds * sample_rate))
    chunks: list[int] = []

    chapters = _get_chapters_seconds(Path(target_path)) if use_chapters else []
    if chapters:
        points: list[dict[str, int | str]] = []
        source_cursor = 0
        for start_second, end_second in chapters:
            start_sec = start_second + chapter_start_offset_seconds
            target_start = int(start_sec * sample_rate)
            target_end = int(end_second * sample_rate)
            if target_end <= target_start:
                continue
            if target_start >= target_len:
                break
            target_end = min(target_end, target_len)

            chapter_duration = target_end - target_start

            search_start = max(0, min(source_cursor, source_len - 1))
            search_end = min(
                source_len, search_start + int(chapter_duration * chapter_search_factor)
            )
            if search_end - search_start <= chapter_duration:
                continue

            start_offset, start_quality = _align_scipy(
                source_audio[0],
                target_audio[0],
                search_start,
                search_end,
                target_start,
                target_end,
            )
            if start_quality >= threshold:
                aligned_start = search_start + start_offset
            else:
                aligned_start = search_start
            aligned_start = max(0, min(aligned_start, source_len - 1))
            aligned_end = aligned_start + chapter_duration
            aligned_end = max(0, min(aligned_end, source_len))

            if aligned_end > aligned_start:
                start_frame = round(aligned_start * fps / sample_rate)
                end_frame = round(aligned_end * fps / sample_rate)
                if end_frame > start_frame:
                    points.append(
                        {"in": start_frame, "out": end_frame, "point": "nopoint"}
                    )
                source_cursor = aligned_end + int(chapter_min_gap_seconds * sample_rate)

        return points

    start = 0
    next_step = start + search_window_factor * buffer
    backward = False
    for i in range(0, target_len - (target_len % buffer), buffer):
        nxt, quality = _align_scipy(
            source_audio[0], target_audio[0], start, next_step, i, i + buffer
        )
        if quality > threshold:
            backward = True
            start += nxt
            next_step = refine_window_factor * buffer + start
            chunks.append(start)
        else:
            if backward:
                backward = False
            if not chunks:
                continue
            start = chunks[-1]
            next_step = fallback_window_factor * buffer + start

        next_step = min(next_step, source_len - 1)
        if next_step - start <= buffer:
            break

    if len(chunks) < 2:
        return []

    points: list[dict[str, int | str]] = []
    last = 0
    for i in range(len(chunks) - 1):
        if last != i and chunks[i + 1] - chunks[i] > buffer * segment_gap_factor:
            start_frame = round(chunks[last] * fps / sample_rate)
            end_frame = round(chunks[i] * fps / sample_rate)
            if end_frame > start_frame:
                points.append({"in": start_frame, "out": end_frame, "point": "nopoint"})
            last = i + 1
    start_frame = round(chunks[last] * fps / sample_rate)
    end_frame = round(chunks[-1] * fps / sample_rate)
    if end_frame > start_frame:
        points.append({"in": start_frame, "out": end_frame, "point": "nopoint"})

    return points
