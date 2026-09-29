"""Cut detection from a rendered video."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import librosa
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector, ThresholdDetector

from jugger_video_manipulation.ffmpeg_utils import extract_audio, get_chapters, get_fps

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np


def prepare_segments(
    *,
    rush_files: list[Path],
    edited_file: Path,
    tmp_dir_path: Path,
    sample_rate: int = 22050,
) -> list[dict[str, int | str]]:
    """Prepare segments for cutting using Librosa.

    Args:
        rush_files : list of Path to rush audio files
        edited_file : Path to edited video file
        tmp_dir_path : Path to temporary directory for audio processing
        sample_rate : sampling rate for audio processing
    return:
        list of pairs in, out
    """
    margin = 1.0  # ignorer 1s aux bords pour éviter les fondus
    hop_length = 512

    rush_audio = tmp_dir_path / f"{uuid.uuid4().hex}_rush_audio.wav"
    rendered_audio = tmp_dir_path / f"{uuid.uuid4().hex}_rendered_audio.wav"

    extract_audio(rush_files, rush_audio, sample_rate=sample_rate)
    extract_audio([edited_file], rendered_audio, sample_rate=sample_rate)

    # 2. Détecter les segments dans le fichier monté
    segments = get_chapters(edited_file)
    if not segments:
        # Fallback : détection par PySceneDetect
        segments = detect_scenes(edited_file)  # à implémenter

    y_rush, _ = librosa.load(rush_audio, sr=sample_rate, mono=True)
    rush_chroma = librosa.feature.chroma_cens(
        y=y_rush, sr=sample_rate, hop_length=hop_length
    )

    # 4. Pour chaque segment du montage, trouver le in/out dans les rushs
    results = []
    last_t_out = 0.0
    for seg_in, seg_out in segments:
        search_start = max(0.0, last_t_out)
        search_end = None
        results.append(
            find_segment_in_rush_(
                segment_path=rendered_audio,
                seg=(seg_in + margin, seg_out - margin),
                hop_length=hop_length,
                rush_path=rush_audio,
                rush_chroma=rush_chroma,
                sample_rate=sample_rate,
                search_start_end=(search_start, search_end),
            )
        )
    fps = get_fps(edited_file)
    return [
        {
            "in": int((start - margin) * fps),
            "out": int((end + margin) * fps),
            "point": "nopoint",
        }
        for start, end in results
    ]


def detect_scenes(
    edited_file: Path,
    threshold_fade: float = 8.0,  # sensibilité détection fondus
    threshold_cut: float = 27.0,  # sensibilité détection cuts secs
) -> list[tuple[float, float]]:
    """Detect scenes in a video using SceneManager with ThresholdDetector and ContentDetector.

    Args:
        edited_file (Path): Path to the edited video file.
        threshold_fade (float, optional): Threshold for fade detection. Defaults to 8.0.
        threshold_cut (float, optional): Threshold for cut detection. Defaults to 27.0.

    Returns:
        list[tuple[float, float]]: List of scene start and end times.
    """
    video = open_video(str(edited_file))
    scene_manager = SceneManager()

    # ThresholdDetector → fondus (transitions douces)
    # ContentDetector  → cuts secs
    scene_manager.add_detector(ThresholdDetector(threshold=threshold_fade))
    scene_manager.add_detector(ContentDetector(threshold=threshold_cut))

    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    # Convertir en list[tuple[float, float]] — même format que get_chapters()
    return [(start.get_seconds(), end.get_seconds()) for start, end in scene_list]


def find_segment_in_rush_(
    *,
    segment_path: Path,
    seg: tuple[float, float],
    rush_path: Path | None,
    rush_chroma: np.ndarray | None = None,  # rush_chroma: np.ndarray | None = None,
    hop_length: int = 128,
    sample_rate: int = 22050,
    search_start_end: tuple[float, float | None] = (0, None),
):
    """Finds the segment in rushs using Librosa.

    Args:
        segment_path (Path): Path to the segment audio file
        seg (tuple[float, float]): Start and end times of the segment in seconds
        rush_path (Path | None): Path to the rush audio file, or None if rush_chroma is provided
        rush_chroma (np.ndarray | None, optional): Pre-computed chroma features for rush audio. Defaults to None.
        hop_length (int, optional): Hop length for feature extraction. Defaults to 128.
        sample_rate (int, optional): Sample rate for audio loading. Defaults to 22050.
        search_start_end (tuple[float, float | None], optional): Start and end times to
            search for the segment in rushs. Defaults to (0, None).
    """
    seg_in, seg_out = seg
    y_seg, _ = librosa.load(
        segment_path,
        sr=sample_rate,
        mono=True,
        offset=seg_in,
        duration=(seg_out - seg_in),
    )
    seg_chroma = librosa.feature.chroma_cens(
        y=y_seg, sr=sample_rate, hop_length=hop_length
    )

    # 2. Extraire les features (chroma_cens = robuste au bruit/compression)
    if rush_chroma is None and rush_path is None:
        raise ValueError("Either rush_path or rush_chroma must be provided")
    if rush_chroma is None:
        rush_chroma, _ = librosa.load(rush_path, sr=sample_rate, mono=True)
        rush_chroma = librosa.feature.chroma_cens(
            y=rush_chroma, sr=sample_rate, hop_length=hop_length
        )

    frame_start = librosa.time_to_frames(
        search_start_end[0], sr=sample_rate, hop_length=hop_length
    ).item()
    frame_end = (
        librosa.time_to_frames(
            search_start_end[1], sr=sample_rate, hop_length=hop_length
        ).item()
        if search_start_end[1]
        else rush_chroma.shape[1]
    )

    # 3. Subsequence DTW — cherche seg dans rush
    _, wp = librosa.sequence.dtw(
        X=seg_chroma,
        Y=rush_chroma[:, frame_start:frame_end],
        metric="cosine",
        subseq=True,  # ← clé : cherche une sous-séquence, pas un alignement global
    )

    # 4. Extraire l'offset
    # wp[-1, 1] = frame dans le rush où le segment se termine
    end_frame = wp[0, 1] + frame_start
    start_frame = wp[-1, 1] + frame_start

    t_in = librosa.frames_to_time(start_frame, sr=sample_rate, hop_length=hop_length)
    t_out = librosa.frames_to_time(end_frame, sr=sample_rate, hop_length=hop_length)

    return t_in, t_out
