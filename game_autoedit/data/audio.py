"""Audio extraction and windowed reads.

Archives live on a network share and are several hundred megabytes each. They
are decoded once into 16 kHz mono WAV in the local cache; training then reads
windows out of those with a seek, never touching the share again.

A game with no archive yet is decoded from its rushes instead, which is why
extraction takes a list of sources and concatenates them: the archive is that
same concatenation, so both give one timeline.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf

from game_autoedit.config import CHANNELS, SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
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
    channels: int = 1

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


def probe_fps(path: Path) -> float | None:
    """Return the frame rate of a media file's first video stream, or None.

    Rushes carry no VideoFile row, so their rate is read off the file itself.
    """
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
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
        rate = json.loads(result.stdout)["streams"][0]["r_frame_rate"]
        numerator, denominator = (float(part) for part in rate.split("/"))
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return None
    return numerator / denominator if denominator else None


def _extract_command(
    sources: Sequence[Path],
    destination: Path,
    *,
    sample_rate: int,
    channels: int,
) -> list[str]:
    """Build the ffmpeg call that decodes `sources` into one WAV.

    Several sources are concatenated, each normalised to the target format
    first: the concat filter refuses segments that disagree on rate or channel
    layout, and rushes from two different cameras regularly do.
    """
    command = [FFMPEG, "-nostdin", "-v", "error", "-y"]
    for source in sources:
        command += ["-i", str(source)]

    if len(sources) > 1:
        layout = "mono" if channels == 1 else "stereo"
        normalised = "".join(
            f"[{index}:a:0]aformat=sample_rates={sample_rate}:"
            f"channel_layouts={layout}[a{index}];"
            for index in range(len(sources))
        )
        labels = "".join(f"[a{index}]" for index in range(len(sources)))
        command += [
            "-filter_complex",
            f"{normalised}{labels}concat=n={len(sources)}:v=0:a=1[out]",
            "-map",
            "[out]",
        ]

    return [
        *command,
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]


def extract_audio(
    sources: Sequence[Path] | Path,
    destination: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
) -> None:
    """Decode one or more media files to a single PCM16 WAV at `sample_rate`.

    Writes to a temporary neighbour first, so an interrupted run never leaves a
    truncated file that a later run would take for valid.

    Args:
        sources: the file to decode, or the files to concatenate in order.
        destination: where the WAV is written.
        sample_rate: the cache's sample rate.
        channels: how many channels to keep.

    Raises:
        AudioExtractionError: ffmpeg failed, or wrote nothing.
    """
    files = [sources] if isinstance(sources, PurePath) else list(sources)
    if not files:
        raise AudioExtractionError("aucune source audio à extraire")

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".partial.wav")
    result = subprocess.run(
        _extract_command(files, tmp, sample_rate=sample_rate, channels=channels),
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        named = ", ".join(str(file) for file in files)
        raise AudioExtractionError(f"ffmpeg a échoué sur {named}: {result.stderr}")
    tmp.replace(destination)


def _marker_path(destination: Path) -> Path:
    """Return the sidecar recording which files a cached track was made of."""
    return destination.with_suffix(".sources.json")


def _marker(game: LabeledGame) -> dict[str, Any]:
    """Return the provenance to record next to an extracted track."""
    return {
        "quality": game.quality,
        "sources": [str(source) for source in game.audio_sources],
    }


def _cache_matches(destination: Path, game: LabeledGame) -> bool:
    """Tell whether the cached track was extracted from this game's sources.

    A cache with no sidecar is trusted: the 268 tracks extracted before the
    sidecar existed all came from archives, and re-extracting them to learn
    what is already known would cost a night.

    What this guards is the other direction: a game proposed from its rushes
    and archived afterwards must not hand its rush audio to training, which
    was measured on one audio profile only.
    """
    marker = _marker_path(destination)
    if not marker.exists():
        return True
    try:
        return bool(json.loads(marker.read_text()) == _marker(game))
    except (OSError, json.JSONDecodeError):
        return False


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
        channels=int(info.channels),
    )


def build_audio_cache(
    games: Iterable[LabeledGame],
    *,
    cache_dir: Path,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
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
        if (
            existing is not None
            and existing.sample_rate == sample_rate
            and existing.channels == channels
            and _cache_matches(destination, game)
        ):
            yield game, existing, None
            continue

        try:
            extract_audio(
                game.audio_sources,
                destination,
                sample_rate=sample_rate,
                channels=channels,
            )
        except AudioExtractionError as error:
            yield game, None, str(error)
            continue
        _marker_path(destination).write_text(json.dumps(_marker(game), indent=2))

        cached = audio_info(destination)
        if cached is None:
            yield game, None, "fichier extrait illisible"
            continue
        yield game, cached, None


def read_window(
    path: Path,
    start: float,
    duration: float,
    *,
    sample_rate: int = SAMPLE_RATE,
    mono: bool = True,
) -> np.ndarray:
    """Read `duration` seconds starting at `start`, as float32 in [-1, 1].

    Reads past the end are zero-padded, so a window near the last second of a
    game still comes back at the expected length.

    Args:
        path: the cached WAV.
        start: where to start, in seconds.
        duration: how long to read, in seconds.
        sample_rate: the cache's sample rate.
        mono: downmix to one channel. False returns ``(samples, channels)``,
            which is what the spatial features need.

    Returns:
        ``(samples,)`` when mono, ``(samples, channels)`` otherwise.
    """
    want = int(round(duration * sample_rate))
    offset = int(round(start * sample_rate))

    with sf.SoundFile(str(path)) as handle:
        channels = handle.channels
        if offset >= handle.frames:
            chunk = np.zeros((0, channels), dtype=np.float32)
        else:
            handle.seek(max(offset, 0))
            chunk = handle.read(want, dtype="float32", always_2d=True)

    if offset < 0:
        chunk = np.concatenate([np.zeros((-offset, channels), dtype=np.float32), chunk])
    if len(chunk) < want:
        chunk = np.concatenate(
            [chunk, np.zeros((want - len(chunk), channels), dtype=np.float32)]
        )

    window: np.ndarray = chunk[:want].astype(np.float32, copy=False)
    return window.mean(axis=1) if mono else window


def mid_side(stereo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a stereo signal into its mid and side components.

    Mid is what a mono downmix would have kept; side is everything the two
    microphones disagree on, which is where the direction of a sound lives. On
    a dual-mono recording the side channel is silence, and the model has to
    cope with that — five of the archived tournaments are like this.

    Args:
        stereo: ``(samples, channels)``.

    Returns:
        The mid and side signals, each ``(samples,)``.
    """
    if stereo.ndim == 1:
        return stereo, np.zeros_like(stereo)
    left = stereo[:, 0]
    right = stereo[:, 1] if stereo.shape[1] > 1 else stereo[:, 0]
    return (left + right) / 2.0, (left - right) / 2.0
