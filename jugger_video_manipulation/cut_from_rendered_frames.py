"""Frame-based cut detection from a rendered video."""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Iterable
from pathlib import Path

import ffmpeg  # type: ignore[import-untyped]
import numpy as np
from PIL import Image
from tqdm import tqdm


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


def _extract_sampled_frames(
    input_path: Path,
    output_dir: Path,
    *,
    fps: float,
    prefix: str,
    is_concat: bool = False,
) -> list[Path]:
    _ensure_dir(output_dir)
    pattern = output_dir / f"{prefix}_%06d.jpg"
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if is_concat:
        args.extend(["-f", "concat", "-safe", "0", "-i", str(input_path)])
    else:
        args.extend(["-i", str(input_path)])
    args.extend(
        [
            "-vf",
            f"fps={fps}",
            "-q:v",
            "2",
            str(pattern),
        ]
    )
    subprocess.run(args, check=True)
    return sorted(output_dir.glob(f"{prefix}_*.jpg"))


def _dhash(
    image_path: Path,
    *,
    hash_size: int = 8,
    ignore_bottom_fraction: float = 1 / 3,
) -> np.ndarray:
    image = Image.open(image_path).convert("L")
    width, height = image.size
    if 0 < ignore_bottom_fraction < 1:
        crop_height = int(height * (1 - ignore_bottom_fraction))
        if crop_height > 0:
            image = image.crop((0, 0, width, crop_height))
    image = image.resize((hash_size + 1, hash_size), Image.BILINEAR)
    pixels = np.asarray(image)
    diff = pixels[:, 1:] > pixels[:, :-1]
    return diff.flatten().astype(np.uint8)


def _hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def _chunked(iterable: Iterable[Path], size: int) -> Iterable[list[Path]]:
    chunk: list[Path] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def build_cut_points_from_rendered_frames(
    source_dir: str | Path,
    source_files: list[str],
    target_path: str | Path,
    *,
    source_proxy_path: str | Path | None = None,
    sample_interval_seconds: float = 0.5,
    match_max_distance: int = 10,
    search_window_seconds: float = 30.0,
    miss_advance_seconds: float = 0.0,
    target_start_skip_seconds: float = 5.0,
    segment_gap_seconds: float = 2.0,
    hash_size: int = 64,
    ignore_bottom_fraction: float = 1 / 3,
    use_chapters: bool = True,
    chapter_search_factor: float = 2.0,
    chapter_min_gap_seconds: float = 30.0,
    chapter_start_offset_seconds: float = 1.0,
    unordered: bool = False,
    force_unchaptered: bool = False,
    tmp_dir: str | Path = "core/tmp",
) -> list[dict[str, int | str]]:
    """Build cut points using frame hashes instead of audio.

    The algorithm samples frames every `sample_interval_seconds` from the source
    and target, computes a perceptual hash per frame, then greedily matches
    target frames against a sliding window in the source. Unmatched target
    frames are treated as ads or overlays that do not exist in the source.

    Tuning parameters:
        source_proxy_path: Optional pre-concatenated proxy video to sample.
        sample_interval_seconds: Sampling period in seconds (e.g. 0.5s).
        match_max_distance: Max Hamming distance to accept a match.
        search_window_seconds: How far to search ahead in source for matches.
        miss_advance_seconds: Source advancement on miss to avoid stalling.
        target_start_skip_seconds: Seconds to skip at target start for matching.
        segment_gap_seconds: Gap in source seconds to start a new segment.
        hash_size: Perceptual hash size (hash_size * hash_size bits).
        ignore_bottom_fraction: Fraction of the image height to ignore from the bottom.
        use_chapters: When True, align per chapter if chapters exist.
        chapter_search_factor: Multiplier for chapter-duration search range.
        chapter_min_gap_seconds: Minimum gap in source seconds between chapters.
        chapter_start_offset_seconds: Seconds to skip at chapter start for matching.
        unordered: When True, ignore chapter ordering and collisions in source.
        force_unchaptered: Force unchaptered matching even if chapters exist.
        tmp_dir: Directory for temp files.
    """
    sample_fps = 1.0 / max(sample_interval_seconds, 1e-6)
    tmp_root = Path(tmp_dir)
    source_tmp = tmp_root / f"frame_source_{uuid.uuid4().hex}"
    target_tmp = tmp_root / f"frame_target_{uuid.uuid4().hex}"

    source_proxy = Path(source_proxy_path) if source_proxy_path else None
    if source_proxy and source_proxy.exists():
        print("Extracting source frames from proxy...")
        source_frames = _extract_sampled_frames(
            source_proxy, source_tmp, fps=sample_fps, prefix="src"
        )
    else:
        print("Extracting source frames from concatenated sources...")
        concat_path = _build_concat_file(Path(source_dir), source_files, tmp_root)
        source_frames = _extract_sampled_frames(
            concat_path, source_tmp, fps=sample_fps, prefix="src", is_concat=True
        )
    print("Extracting target frames...")
    target_frames = _extract_sampled_frames(
        Path(target_path), target_tmp, fps=sample_fps, prefix="tgt"
    )

    if not source_frames or not target_frames:
        return []

    print("Computing source hashes...")
    source_hashes = [
        _dhash(path, hash_size=hash_size, ignore_bottom_fraction=ignore_bottom_fraction)
        for path in tqdm(source_frames, desc="Source hashes", ascii=True)
    ]
    print("Computing target hashes...")
    target_hashes = [
        _dhash(path, hash_size=hash_size, ignore_bottom_fraction=ignore_bottom_fraction)
        for path in tqdm(target_frames, desc="Target hashes", ascii=True)
    ]

    search_window = max(1, int(search_window_seconds * sample_fps))
    miss_advance = int(miss_advance_seconds * sample_fps)

    def match_range(
        target_range: range,
        source_start_idx: int,
        *,
        window_size: int,
    ) -> list[int]:
        matches_local: list[int] = []
        source_idx = source_start_idx
        for target_idx in target_range:
            window_end = min(len(source_hashes), source_idx + window_size)
            best_idx = None
            best_dist = None
            for cand_idx in range(source_idx, window_end):
                dist = _hamming(target_hashes[target_idx], source_hashes[cand_idx])
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx = cand_idx
                    if best_dist == 0:
                        break
            if best_dist is not None and best_dist <= match_max_distance:
                matches_local.append(best_idx)
                source_idx = best_idx + 1
            else:
                source_idx = min(len(source_hashes) - 1, source_idx + miss_advance)
        return matches_local

    def match_chaptered(
        *,
        chapters: list[tuple[float, float]],
        fps: float,
    ) -> list[dict[str, int | str]]:
        skip_start_idx = int(target_start_skip_seconds * sample_fps)
        points: list[dict[str, int | str]] = []
        print(f"Chapters detected: {len(chapters)}")
        for start_sec, end_sec in tqdm(chapters, desc="Chapter match", ascii=True):
            start_sec += chapter_start_offset_seconds
            if end_sec <= start_sec:
                continue
            target_start_idx = int(start_sec * sample_fps)
            if start_sec <= target_start_skip_seconds:
                target_start_idx = max(skip_start_idx, target_start_idx)
            target_end_idx = min(len(target_hashes), int(end_sec * sample_fps))
            if target_end_idx <= target_start_idx:
                continue
            chapter_len = target_end_idx - target_start_idx
            if chapter_len <= 0:
                continue

            mid_sec = (start_sec + end_sec) / 2.0
            window_start = mid_sec - 2.5
            window_times = [window_start + offset for offset in range(5)]
            target_indices: list[int] = []
            for t in window_times:
                idx = int(t * sample_fps)
                if idx < target_start_idx:
                    idx = target_start_idx
                if idx >= target_end_idx:
                    idx = target_end_idx - 1
                target_indices.append(idx)
            if not target_indices:
                continue

            first_idx = target_indices[0]
            offsets = [idx - first_idx for idx in target_indices]

            candidates: list[tuple[int, int]] = []
            for cand_idx, source_hash in enumerate(source_hashes):
                dist = _hamming(target_hashes[first_idx], source_hash)
                candidates.append((dist, cand_idx))
            if not candidates:
                continue
            candidates.sort(key=lambda item: item[0])
            candidates = candidates[:1000]

            best_start = None
            best_avg = None
            for _, cand_start in candidates:
                total_dist = 0
                valid = True
                for offset, target_idx in zip(offsets, target_indices, strict=True):
                    src_idx = cand_start + offset
                    if src_idx < 0 or src_idx >= len(source_hashes):
                        valid = False
                        break
                    total_dist += _hamming(
                        target_hashes[target_idx], source_hashes[src_idx]
                    )
                if not valid:
                    continue
                avg_dist = total_dist / len(target_indices)
                if best_avg is None or avg_dist < best_avg:
                    best_avg = avg_dist
                    best_start = cand_start

            if best_start is None:
                continue

            offset = best_start - first_idx
            matched_start = target_start_idx + offset
            matched_end = target_end_idx + offset
            if matched_end > matched_start:
                start_frame = round(matched_start * sample_interval_seconds * fps)
                end_frame = round(matched_end * sample_interval_seconds * fps)
                if end_frame > start_frame:
                    target_duration = end_sec - start_sec
                    cut_duration = (end_frame - start_frame) / fps
                    print(
                        "Chapter match score:",
                        f"{best_avg:.2f}" if best_avg is not None else "n/a",
                        "in/out:",
                        f"{start_frame}/{end_frame}",
                        "duration:",
                        f"{cut_duration:.2f}s (chapter {target_duration:.2f}s)",
                    )
                    points.append(
                        {"in": start_frame, "out": end_frame, "point": "nopoint"}
                    )

        return points

    def match_unchaptered(*, fps: float) -> list[dict[str, int | str]]:
        skip_start_idx = int(target_start_skip_seconds * sample_fps)
        source_idx = 0
        matches: list[int] = []
        total_targets = max(0, len(target_hashes) - skip_start_idx)
        for target_idx in tqdm(
            range(skip_start_idx, len(target_hashes)),
            total=total_targets,
            desc="Frame match",
            ascii=True,
        ):
            matched = match_range(
                range(target_idx, target_idx + 1),
                source_idx,
                window_size=search_window,
            )
            if matched:
                matches.append(matched[0])
                source_idx = matched[0] + 1
            else:
                source_idx = min(len(source_hashes) - 1, source_idx + miss_advance)

        if not matches:
            return []

        gap_frames = int(segment_gap_seconds * sample_fps)
        points: list[dict[str, int | str]] = []
        segment_start = matches[0]
        last_source = matches[0]
        for src_idx in matches[1:]:
            if src_idx - last_source > gap_frames:
                start_frame = round(segment_start * sample_interval_seconds * fps)
                end_frame = round(last_source * sample_interval_seconds * fps)
                if end_frame > start_frame:
                    points.append(
                        {"in": start_frame, "out": end_frame, "point": "nopoint"}
                    )
                segment_start = src_idx
            last_source = src_idx
        start_frame = round(segment_start * sample_interval_seconds * fps)
        end_frame = round(last_source * sample_interval_seconds * fps)
        if end_frame > start_frame:
            points.append({"in": start_frame, "out": end_frame, "point": "nopoint"})

        return points

    fps_source_path = source_proxy if source_proxy and source_proxy.exists() else None
    if fps_source_path is None:
        fps_source_path = Path(source_dir) / "rushs" / source_files[0]
    fps = _pick_video_fps(fps_source_path)

    target_video_path = Path(target_path)
    chapters = _get_chapters_seconds(target_video_path) if use_chapters else []
    if chapters and not force_unchaptered:
        return match_chaptered(chapters=chapters, fps=fps)
    return match_unchaptered(fps=fps)
