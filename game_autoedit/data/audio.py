"""Audio extraction and windowed reads.

Archives live on a network share and are several hundred megabytes each. They
are decoded once into 16 kHz mono WAV in the local cache; training then reads
windows out of those with a seek, never touching the share again.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf

from game_autoedit.config import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from game_autoedit.data.catalog import LabeledGame

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class AudioExtractionError(RuntimeError):
    """Raised when ffmpeg fails to decode an archive."""


@dataclass(frozen=True)
class CachedAudio:
    """One extracted audio track."""

    game_id: int
    path: Path
    sample_rate: int
    frames: int

    @property
    def duration(self) -> float:
        """Return the track duration in seconds."""
        return self.frames / self.sample_rate


def probe_duration(path: Path) -> float | None:
    """Return the duration of a media file in seconds, or None if unreadable."""
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def extract_audio(
    source: Path, destination: Path, *, sample_rate: int = SAMPLE_RATE
) -> None:
    """Decode a media file to mono PCM16 WAV at `sample_rate`.

    Writes to a temporary neighbour first, so an interrupted run never leaves a
    truncated file that a later run would take for valid.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".partial.wav")
    result = subprocess.run(
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(tmp),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise AudioExtractionError(f"ffmpeg a échoué sur {source}: {result.stderr}")
    tmp.replace(destination)


def audio_info(path: Path) -> CachedAudio | None:
    """Return the cached track description, or None if the file is unusable."""
    if not path.exists():
        return None
    try:
        info = sf.info(str(path))
    except sf.LibsndfileError:
        return None
    game_id = int(path.stem.removeprefix("game_"))
    return CachedAudio(
        game_id=game_id,
        path=path,
        sample_rate=int(info.samplerate),
        frames=int(info.frames),
    )


def build_audio_cache(
    games: Iterable[LabeledGame],
    *,
    cache_dir: Path,
    sample_rate: int = SAMPLE_RATE,
    force: bool = False,
) -> Iterator[tuple[LabeledGame, CachedAudio | None, str | None]]:
    """Extract the audio of every game, yielding progress as it goes.

    Yields:
        For each game: the game, its cached track when the extraction worked,
        and an error message when it did not.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    for game in games:
        destination = cache_dir / f"game_{game.game_id}.wav"
        existing = None if force else audio_info(destination)
        if existing is not None and existing.sample_rate == sample_rate:
            yield game, existing, None
            continue

        try:
            extract_audio(game.audio_source, destination, sample_rate=sample_rate)
        except AudioExtractionError as error:
            yield game, None, str(error)
            continue

        cached = audio_info(destination)
        if cached is None:
            yield game, None, "fichier extrait illisible"
            continue
        yield game, cached, None


def read_window(
    path: Path, start: float, duration: float, *, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """Read `duration` seconds starting at `start`, as float32 in [-1, 1].

    Reads past the end are zero-padded, so a window near the last second of a
    game still comes back at the expected length.
    """
    want = int(round(duration * sample_rate))
    offset = int(round(start * sample_rate))
    with sf.SoundFile(str(path)) as handle:
        if offset >= handle.frames:
            return np.zeros(want, dtype=np.float32)
        handle.seek(max(offset, 0))
        chunk = handle.read(want, dtype="float32", always_2d=False)

    if offset < 0:
        chunk = np.concatenate([np.zeros(-offset, dtype=np.float32), chunk])
    if len(chunk) < want:
        chunk = np.concatenate([chunk, np.zeros(want - len(chunk), dtype=np.float32)])
    window: np.ndarray = chunk[:want].astype(np.float32, copy=False)
    return window
